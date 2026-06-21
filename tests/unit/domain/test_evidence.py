# tests/unit/domain/test_evidence.py
from docs.domain.evidence import ManualFileFact, TraceabilityFact, build_manifest


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
    assert manifest["policy"]["normative_source"] == "tesina/guides/manual-estadia-tic"
    assert manifest["policy"]["pdf_and_extracted_use"] == "rules_traceability_only"
    assert manifest["policy"]["apa_style"] == "APA 7"


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
