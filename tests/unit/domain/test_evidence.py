# tests/unit/domain/test_evidence.py
import inspect

from docs.domain import evidence as evidence_module
from docs.domain.evidence import (
    ManualFileFact,
    ManualHashFact,
    PromptHashFileFact,
    SourceHashFileFact,
    TraceabilityFact,
    build_manifest,
    build_prompt_hash_payload,
    build_rules_hash_payload,
    build_source_hash_payload,
)


def test_module_source_has_no_tesina_literal():
    assert "tesina" not in inspect.getsource(evidence_module).lower()


def _manual_file(**overrides) -> ManualFileFact:
    defaults = dict(
        path="/repo/manual/00-intro.md",
        name="00-intro.md",
        sha256="a" * 64,
        headings=["Introducción"],
        excerpt="Texto de ejemplo.",
    )
    defaults.update(overrides)
    return ManualFileFact(**defaults)


def _traceability(**overrides) -> TraceabilityFact:
    defaults = dict(path="/repo/manual.pdf", type="institutional_pdf", sha256="b" * 64, size=1024)
    defaults.update(overrides)
    return TraceabilityFact(**defaults)


def _call(**overrides):
    defaults = dict(
        manual_files=[],
        traceability=[],
        advisor_overrides=[],
        draft_mode={},
        strict_mode={},
        preliminaries={},
        format={},
        apa7={},
        privacy={},
        section_contracts={},
        contract_hashes={},
    )
    defaults.update(overrides)
    return build_manifest(**defaults)


def test_build_manifest_schema_and_fixed_policy_fields():
    manifest = _call()
    assert manifest["schema"] == 1
    assert manifest["policy"]["pdf_and_extracted_use"] == "rules_traceability_only"
    assert manifest["policy"]["apa_style"] == "APA 7"


def test_build_manifest_normative_source_defaults_to_empty_string_not_hardcoded():
    # spec: document-template "No hardcoded document-type literal in domain
    # code" (evidence.py #7) -- normative_source is a template-declared
    # parameter, never a fixed "docs/guides/manual-estadia-tic" literal.
    manifest = _call()
    assert manifest["policy"]["normative_source"] == ""


def test_build_manifest_normative_source_comes_from_parameter():
    manifest = _call(normative_source="docs/guides/manual-estadia-tic")
    assert manifest["policy"]["normative_source"] == "docs/guides/manual-estadia-tic"


def test_build_manifest_policy_carries_advisor_overrides_and_modes():
    overrides = [{"id": "x", "status": "active"}]
    draft = {"allow_pending": True}
    strict = {"allow_pending": False}
    manifest = _call(advisor_overrides=overrides, draft_mode=draft, strict_mode=strict)
    assert manifest["policy"]["advisor_overrides"] == overrides
    assert manifest["policy"]["draft_mode"] == draft
    assert manifest["policy"]["strict_mode"] == strict


def test_build_manifest_advisor_overrides_duplicated_at_top_level_verbatim_legacy():
    overrides = [{"id": "x", "status": "active"}]
    manifest = _call(advisor_overrides=overrides)
    assert manifest["advisor_overrides"] == overrides
    assert manifest["policy"]["advisor_overrides"] == overrides


def test_build_manifest_manual_files_serialized_from_facts():
    fact = _manual_file()
    manifest = _call(manual_files=[fact])
    assert manifest["manual_files"] == [
        {
            "path": fact.path,
            "name": fact.name,
            "sha256": fact.sha256,
            "headings": fact.headings,
            "excerpt": fact.excerpt,
        }
    ]


def test_build_manifest_traceability_serialized_from_facts():
    fact = _traceability()
    manifest = _call(traceability=[fact])
    assert manifest["traceability"] == [
        {"path": fact.path, "type": fact.type, "sha256": fact.sha256, "size": fact.size}
    ]


def test_build_manifest_preserves_manual_files_order():
    first = _manual_file(name="00-intro.md")
    second = _manual_file(name="01-objetivos.md")
    manifest = _call(manual_files=[first, second])
    assert [f["name"] for f in manifest["manual_files"]] == ["00-intro.md", "01-objetivos.md"]


def test_build_manifest_passes_through_format_apa7_privacy_preliminaries():
    manifest = _call(
        preliminaries={"roman_pagination": {"enabled": True}},
        format={"page_margins_cm": {}},
        apa7={"enabled": True},
        privacy={"redact": True},
    )
    assert manifest["preliminaries"] == {"roman_pagination": {"enabled": True}}
    assert manifest["format"] == {"page_margins_cm": {}}
    assert manifest["apa7"] == {"enabled": True}
    assert manifest["privacy"] == {"redact": True}


def test_build_manifest_section_contracts_and_hashes_passed_through():
    contracts = {"intro": {"title": "Introducción"}}
    hashes = {"intro": "c" * 64}
    manifest = _call(section_contracts=contracts, contract_hashes=hashes)
    assert manifest["section_contracts"] == contracts
    assert manifest["contract_hashes"] == hashes


def test_build_manifest_empty_inputs_produce_empty_lists_and_dicts():
    manifest = _call()
    assert manifest["manual_files"] == []
    assert manifest["traceability"] == []
    assert manifest["section_contracts"] == {}
    assert manifest["contract_hashes"] == {}


def test_build_rules_hash_payload_assembles_expected_keys():
    fact = ManualHashFact(path="/repo/manual/00-intro.md", sha256="a" * 64)
    payload = build_rules_hash_payload(
        manual_files=[fact],
        section_contracts={"intro": {"title": "Introducción"}},
        format={"page_margins_cm": {}},
        apa7={"enabled": True},
        structure=[{"type": "cover"}],
        preliminaries={"roman_pagination": {"enabled": True}},
    )
    assert payload == {
        "manual_dir": [{"path": fact.path, "sha256": fact.sha256}],
        "section_contracts": {"intro": {"title": "Introducción"}},
        "format": {"page_margins_cm": {}},
        "apa7": {"enabled": True},
        "structure": [{"type": "cover"}],
        "preliminaries": {"roman_pagination": {"enabled": True}},
    }


def test_build_rules_hash_payload_empty_inputs():
    payload = build_rules_hash_payload(
        manual_files=[], section_contracts={}, format={}, apa7={}, structure=[], preliminaries={}
    )
    assert payload == {
        "manual_dir": [],
        "section_contracts": {},
        "format": {},
        "apa7": {},
        "structure": [],
        "preliminaries": {},
    }


def test_build_rules_hash_payload_preserves_manual_files_order():
    first = ManualHashFact(path="/repo/manual/00-a.md", sha256="a" * 64)
    second = ManualHashFact(path="/repo/manual/01-b.md", sha256="b" * 64)
    payload = build_rules_hash_payload(
        manual_files=[first, second], section_contracts={}, format={}, apa7={}, structure=[], preliminaries={}
    )
    assert [f["path"] for f in payload["manual_dir"]] == [first.path, second.path]


def test_build_source_hash_payload_assembles_files_and_config_sections():
    fact = SourceHashFileFact(path="/repo/context/alumno.md", sha256="a" * 64)
    payload = build_source_hash_payload(files=[fact], config_sections=[{"id": "intro"}])
    assert payload == [
        {"path": fact.path, "sha256": fact.sha256},
        {"config_sections": [{"id": "intro"}]},
    ]


def test_build_source_hash_payload_empty_inputs():
    payload = build_source_hash_payload(files=[], config_sections=[])
    assert payload == [{"config_sections": []}]


def test_build_source_hash_payload_preserves_file_order():
    first = SourceHashFileFact(path="/repo/context/a.md", sha256="a" * 64)
    second = SourceHashFileFact(path="/repo/manual/b.md", sha256="b" * 64)
    payload = build_source_hash_payload(files=[first, second], config_sections=[])
    assert [entry["path"] for entry in payload[:2]] == [first.path, second.path]


def test_build_prompt_hash_payload_uses_bare_filename_under_path_key():
    # Legacy quirk (intentional, verbatim from tesina_harness.py:433-439): the
    # dict key is "path" but the value is the bare filename (path.name), not a
    # full path — prompts are hashed by filename only, unlike source_hash's files.
    fact = PromptHashFileFact(name="section-author.md", sha256="c" * 64)
    payload = build_prompt_hash_payload(files=[fact])
    assert payload == [{"path": "section-author.md", "sha256": fact.sha256}]


def test_build_prompt_hash_payload_empty_inputs():
    assert build_prompt_hash_payload(files=[]) == []


def test_build_prompt_hash_payload_preserves_order():
    first = PromptHashFileFact(name="a.md", sha256="a" * 64)
    second = PromptHashFileFact(name="b.md", sha256="b" * 64)
    payload = build_prompt_hash_payload(files=[first, second])
    assert [entry["path"] for entry in payload] == ["a.md", "b.md"]
