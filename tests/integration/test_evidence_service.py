# tests/integration/test_evidence_service.py
import hashlib
import json
from pathlib import Path

import pytest

from docs.application.evidence import EvidenceService
from docs.infrastructure.persistence.json_evidence_repository import JsonEvidenceRepository


@pytest.fixture
def service() -> EvidenceService:
    return EvidenceService(JsonEvidenceRepository())


def _config(tmp_path: Path, **overrides) -> dict:
    manual_dir = tmp_path / "manual"
    manual_dir.mkdir()
    extracted_dir = tmp_path / "extracted"
    config = {
        "paths": {
            "manual_dir": str(manual_dir),
            "extracted_dir": str(extracted_dir),
            "rules_manifest": str(tmp_path / "manual-rules.json"),
        },
        "section_contracts": {},
        "advisor_overrides": [],
        "strict_policy": {},
        "preliminaries": {},
        "format": {},
        "apa7": {},
        "privacy": {},
    }
    config["paths"].update(overrides.pop("paths", {}))
    config.update(overrides)
    return config


def test_build_rules_with_empty_paths_does_not_raise(tmp_path: Path, service):
    # spec: document-pipeline "Empty paths config does not crash build-rules"
    # -- documento-generico declares `"paths": {}`; only computed paths
    # (rules_manifest) are ever guaranteed present.
    config = {
        "paths": {"rules_manifest": str(tmp_path / "manual-rules.json")},
        "section_contracts": {},
        "advisor_overrides": [],
        "strict_policy": {},
        "preliminaries": {},
        "format": {},
        "apa7": {},
        "privacy": {},
    }

    path = service.build_rules(config)

    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["manual_files"] == []
    assert manifest["traceability"] == []
    assert set(manifest["skipped_paths"]) == {"manual_dir", "extracted_dir"}


def test_build_rules_returns_manifest_path(tmp_path: Path, service):
    config = _config(tmp_path)
    result_path = service.build_rules(config)
    assert result_path == Path(config["paths"]["rules_manifest"])
    assert result_path.exists()


def test_build_rules_hashes_manual_markdown_files(tmp_path: Path, service):
    config = _config(tmp_path)
    manual_dir = Path(config["paths"]["manual_dir"])
    (manual_dir / "00-intro.md").write_text("# Introducción\n\nTexto inicial.")
    path = service.build_rules(config)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert len(manifest["manual_files"]) == 1
    entry = manifest["manual_files"][0]
    assert entry["name"] == "00-intro.md"
    assert entry["headings"] == ["Introducción"]
    assert len(entry["sha256"]) == 64


def test_build_rules_manual_files_sorted_by_filename(tmp_path: Path, service):
    config = _config(tmp_path)
    manual_dir = Path(config["paths"]["manual_dir"])
    (manual_dir / "01-b.md").write_text("# B")
    (manual_dir / "00-a.md").write_text("# A")
    path = service.build_rules(config)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert [f["name"] for f in manifest["manual_files"]] == ["00-a.md", "01-b.md"]


def test_build_rules_skips_missing_manual_pdf_and_example_pdf(tmp_path: Path, service):
    config = _config(tmp_path, paths={"manual_pdf": "", "example_pdf": str(tmp_path / "missing.pdf")})
    path = service.build_rules(config)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["traceability"] == []


def test_build_rules_includes_existing_manual_pdf_as_traceability(tmp_path: Path, service):
    pdf_path = tmp_path / "manual.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    config = _config(tmp_path, paths={"manual_pdf": str(pdf_path)})
    path = service.build_rules(config)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert len(manifest["traceability"]) == 1
    entry = manifest["traceability"][0]
    assert entry["type"] == "institutional_pdf"
    assert entry["size"] == pdf_path.stat().st_size


def test_build_rules_includes_extracted_dir_md_and_json_files(tmp_path: Path, service):
    config = _config(tmp_path)
    extracted_dir = Path(config["paths"]["extracted_dir"])
    extracted_dir.mkdir()
    (extracted_dir / "notes.md").write_text("notas")
    (extracted_dir / "data.json").write_text("{}")
    (extracted_dir / "image.png").write_text("x")
    path = service.build_rules(config)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    entries = {entry["path"].split("/")[-1] for entry in manifest["traceability"]}
    assert entries == {"notes.md", "data.json"}
    assert all(e["type"] == "extracted_traceability" for e in manifest["traceability"])


def test_build_rules_skips_extracted_dir_entirely_when_absent(tmp_path: Path, service):
    config = _config(tmp_path)  # extracted_dir not created
    path = service.build_rules(config)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["traceability"] == []


def test_build_rules_computes_contract_hashes(tmp_path: Path, service):
    contracts = {"intro": {"title": "Introducción", "required_content": ["objetivo"]}}
    config = _config(tmp_path, section_contracts=contracts)
    path = service.build_rules(config)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["section_contracts"] == contracts
    assert set(manifest["contract_hashes"]) == {"intro"}
    assert len(manifest["contract_hashes"]["intro"]) == 64


def test_build_rules_carries_policy_apa7_privacy_preliminaries_format(tmp_path: Path, service):
    config = _config(
        tmp_path,
        strict_policy={"draft": {"allow_pending": True}, "strict": {"allow_pending": False}},
        apa7={"enabled": True},
        privacy={"redact": True},
        preliminaries={"roman_pagination": {"enabled": True}},
        format={"page_margins_cm": {}},
        advisor_overrides=[{"id": "x", "status": "active"}],
    )
    path = service.build_rules(config)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["policy"]["draft_mode"] == {"allow_pending": True}
    assert manifest["policy"]["strict_mode"] == {"allow_pending": False}
    assert manifest["apa7"] == {"enabled": True}
    assert manifest["privacy"] == {"redact": True}
    assert manifest["preliminaries"] == {"roman_pagination": {"enabled": True}}
    assert manifest["format"] == {"page_margins_cm": {}}
    assert manifest["advisor_overrides"] == [{"id": "x", "status": "active"}]
    assert manifest["policy"]["advisor_overrides"] == [{"id": "x", "status": "active"}]


def test_build_rules_second_call_with_unchanged_inputs_does_not_rewrite_generated_at(tmp_path: Path, service):
    config = _config(tmp_path)
    path = service.build_rules(config)
    first = json.loads(path.read_text(encoding="utf-8"))
    path = service.build_rules(config)
    second = json.loads(path.read_text(encoding="utf-8"))
    assert first["generated_at"] == second["generated_at"]


def test_build_rules_second_call_with_new_manual_file_rewrites_manifest(tmp_path: Path, service):
    config = _config(tmp_path)
    service.build_rules(config)
    manual_dir = Path(config["paths"]["manual_dir"])
    (manual_dir / "00-new.md").write_text("# Nuevo")
    path = service.build_rules(config)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert len(manifest["manual_files"]) == 1


def test_rules_hash_returns_file_hash_when_manifest_exists(tmp_path, service):
    config = _config(tmp_path)
    rules_path = service.build_rules(config)  # creates the manifest on disk
    expected = hashlib.sha256(rules_path.read_bytes()).hexdigest()
    assert service.rules_hash(config) == expected


def test_rules_hash_ignores_other_config_fields_when_manifest_exists(tmp_path, service):
    config = _config(tmp_path, section_contracts={"intro": {"title": "Should not matter"}})
    rules_path = service.build_rules(config)
    expected = hashlib.sha256(rules_path.read_bytes()).hexdigest()
    assert service.rules_hash(config) == expected


def test_rules_hash_falls_back_to_synthesized_payload_when_manifest_absent(tmp_path, service):
    config = _config(tmp_path)  # rules_manifest never built
    from pathlib import Path

    manual_dir = Path(config["paths"]["manual_dir"])
    (manual_dir / "00-intro.md").write_text("# Intro", encoding="utf-8")
    result = service.rules_hash(config)
    manual_path = (manual_dir / "00-intro.md").resolve().as_posix()
    manual_sha = hashlib.sha256((manual_dir / "00-intro.md").read_bytes()).hexdigest()
    expected_payload = {
        "manual_dir": [{"path": manual_path, "sha256": manual_sha}],
        "section_contracts": {},
        "format": {},
        "apa7": {},
        "structure": [],
        "preliminaries": {},
    }
    expected = hashlib.sha256(
        json.dumps(expected_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert result == expected


def test_rules_hash_fallback_with_missing_manual_dir_produces_empty_manual_list(tmp_path, service):
    config = _config(tmp_path, paths={"manual_dir": str(tmp_path / "does-not-exist")})
    result = service.rules_hash(config)
    expected_payload = {
        "manual_dir": [], "section_contracts": {}, "format": {}, "apa7": {}, "structure": [], "preliminaries": {},
    }
    expected = hashlib.sha256(
        json.dumps(expected_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert result == expected


def test_contract_hash_hashes_existing_contract(tmp_path, service):
    contracts = {"intro": {"title": "Introducción", "required_content": ["objetivo"]}}
    config = _config(tmp_path, section_contracts=contracts)
    expected = hashlib.sha256(
        json.dumps(contracts["intro"], ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert service.contract_hash(config, "intro") == expected


def test_contract_hash_hashes_empty_dict_when_section_unknown(tmp_path, service):
    config = _config(tmp_path)
    expected = hashlib.sha256(json.dumps({}, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    assert service.contract_hash(config, "unknown") == expected


def test_manifest_hash_empty_string_when_path_value_falsy(service):
    assert service.manifest_hash(None) == ""
    assert service.manifest_hash("") == ""


def test_manifest_hash_empty_string_when_path_missing(tmp_path, service):
    assert service.manifest_hash(str(tmp_path / "missing.json")) == ""


def test_manifest_hash_returns_file_hash_when_path_exists(tmp_path, service):
    path = tmp_path / "source-manifest.json"
    path.write_text('{"a": 1}', encoding="utf-8")
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    assert service.manifest_hash(str(path)) == expected


def _manifest_paths_config(tmp_path: Path, **overrides) -> dict:
    # Manifest paths default to nonexistent files under tmp_path rather than ""
    # — Path("") resolves to the cwd (which exists), so an empty string is not
    # a safe "this manifest is absent" sentinel for file_exists()/read_manifest().
    config = {
        "paths": {
            "source_manifest": str(tmp_path / "source.json"),
            "issues_manifest": str(tmp_path / "issues.json"),
            "code_evidence_manifest": str(tmp_path / "code-evidence.json"),
        },
    }
    config["paths"].update(overrides.pop("paths", {}))
    config.update(overrides)
    return config


def test_load_manifest_facts_dedupes_across_manifests(tmp_path: Path, service):
    source_manifest = Path(tmp_path / "source.json")
    fact = {"classification": "confirmado", "claim": "x", "source": "a"}
    service.repository.write_manifest(source_manifest, {"facts": [fact, fact]})
    config = _manifest_paths_config(tmp_path)

    facts = service.load_manifest_facts(config)

    assert facts == [fact]


def test_load_manifest_facts_collects_facts_and_issues_across_all_three_manifests(tmp_path: Path, service):
    config = _manifest_paths_config(tmp_path)
    service.repository.write_manifest(
        Path(config["paths"]["source_manifest"]), {"facts": [{"classification": "confirmado", "claim": "s1"}]}
    )
    service.repository.write_manifest(
        Path(config["paths"]["issues_manifest"]), {"issues": [{"classification": "pendiente", "claim": "i1"}]}
    )
    service.repository.write_manifest(
        Path(config["paths"]["code_evidence_manifest"]), {"facts": [{"classification": "prototipo", "claim": "c1"}]}
    )

    facts = service.load_manifest_facts(config)

    claims = {f["claim"] for f in facts}
    assert claims == {"s1", "i1", "c1"}


def test_load_manifest_facts_skips_missing_manifest_paths(tmp_path: Path, service):
    config = _manifest_paths_config(tmp_path)  # none of the three files exist

    assert service.load_manifest_facts(config) == []


def test_load_manifest_facts_skips_malformed_json_manifest(tmp_path: Path, service):
    config = _manifest_paths_config(tmp_path)
    Path(config["paths"]["source_manifest"]).write_text("{not valid json", encoding="utf-8")

    assert service.load_manifest_facts(config) == []


def test_load_manifest_facts_ignores_non_dict_items_in_facts_and_issues(tmp_path: Path, service):
    config = _manifest_paths_config(tmp_path)
    service.repository.write_manifest(
        Path(config["paths"]["source_manifest"]),
        {"facts": ["not-a-dict", {"classification": "confirmado", "claim": "ok"}], "issues": [42]},
    )

    facts = service.load_manifest_facts(config)

    assert facts == [{"classification": "confirmado", "claim": "ok"}]


def test_render_fact_ledger_includes_ledger_seed_claim_in_confirmado_group(tmp_path: Path, service):
    config = _manifest_paths_config(tmp_path, ledger_seed=[{"classification": "confirmado", "claim": "Hecho sembrado"}])

    ledger = service.render_fact_ledger(config)

    assert "# Fact Ledger" in ledger
    assert "## Datos confirmados" in ledger
    assert "- Hecho sembrado" in ledger


def test_render_fact_ledger_ledger_seed_defaults_to_confirmado_when_classification_absent(tmp_path: Path, service):
    config = _manifest_paths_config(tmp_path, ledger_seed=[{"claim": "Sin clasificacion"}])

    ledger = service.render_fact_ledger(config)

    assert "## Datos confirmados" in ledger
    assert "- Sin clasificacion" in ledger


def test_render_fact_ledger_omits_empty_groups(tmp_path: Path, service):
    config = _manifest_paths_config(tmp_path)

    ledger = service.render_fact_ledger(config)

    assert ledger == "# Fact Ledger\n"
    assert "## Contradicciones conocidas" not in ledger


def test_render_fact_ledger_includes_caller_supplied_context_lines_in_confirmado_group(tmp_path: Path, service):
    config = _manifest_paths_config(tmp_path)

    ledger = service.render_fact_ledger(config, context_confirmed_lines=["Nombre: Ana"])

    assert "## Datos confirmados" in ledger
    assert "- Nombre: Ana" in ledger


def test_render_fact_ledger_includes_manifest_facts_with_classification_fallback_to_pendiente(tmp_path: Path, service):
    config = _manifest_paths_config(tmp_path)
    service.repository.write_manifest(
        Path(config["paths"]["source_manifest"]), {"facts": [{"claim": "Sin clasificar en manifest"}]}
    )

    ledger = service.render_fact_ledger(config)

    assert "## Pendientes obligatorios" in ledger
    assert "- Sin clasificar en manifest" in ledger


def test_render_fact_ledger_manifest_fact_falls_back_to_title_when_claim_absent(tmp_path: Path, service):
    config = _manifest_paths_config(tmp_path)
    service.repository.write_manifest(
        Path(config["paths"]["source_manifest"]),
        {"issues": [{"classification": "pendiente", "title": "Issue sin claim"}]},
    )

    ledger = service.render_fact_ledger(config)

    assert "- Issue sin claim" in ledger


def test_render_fact_ledger_dedupes_repeated_claims_across_sources(tmp_path: Path, service):
    config = _manifest_paths_config(
        tmp_path,
        ledger_seed=[{"classification": "confirmado", "claim": "Repetido"}],
    )
    service.repository.write_manifest(
        Path(config["paths"]["source_manifest"]), {"facts": [{"classification": "confirmado", "claim": "Repetido"}]}
    )

    ledger = service.render_fact_ledger(config, context_confirmed_lines=["Repetido"])

    assert ledger.count("- Repetido") == 1


def test_render_fact_ledger_covers_all_six_categories_when_reachable(tmp_path: Path, service):
    config = _manifest_paths_config(
        tmp_path,
        ledger_seed=[
            {"classification": "confirmado", "claim": "Confirmado seed"},
            {"classification": "contradiccion", "claim": "Contradiccion seed"},
            {"classification": "pendiente", "claim": "Pendiente seed"},
            {"classification": "prototipo", "claim": "Prototipo seed"},
            {"classification": "fuera_de_alcance", "claim": "Fuera de alcance seed"},
            {"classification": "dato_sensible", "claim": "Dato sensible seed"},
        ],
    )

    ledger = service.render_fact_ledger(config)

    assert "## Datos confirmados" in ledger
    assert "## Contradicciones conocidas" in ledger
    assert "## Pendientes obligatorios" in ledger
    assert "## Prototipos o dependencias externas" in ledger
    assert "## Fuera de alcance del cuerpo" in ledger
    assert "## Datos sensibles excluidos del cuerpo" in ledger
    headings = [
        "## Datos confirmados",
        "## Contradicciones conocidas",
        "## Pendientes obligatorios",
        "## Prototipos o dependencias externas",
        "## Fuera de alcance del cuerpo",
        "## Datos sensibles excluidos del cuerpo",
    ]
    positions = [ledger.index(h) for h in headings]
    assert positions == sorted(positions)


def test_source_hash_hashes_context_and_manual_markdown_files_plus_config_sections(tmp_path: Path, service):
    context_dir = tmp_path / "context"
    context_dir.mkdir()
    (context_dir / "alumno.md").write_text("# Alumno", encoding="utf-8")
    config = _config(tmp_path, paths={"context_dir": str(context_dir)}, sections=[{"id": "intro"}])
    manual_dir = Path(config["paths"]["manual_dir"])
    (manual_dir / "00-intro.md").write_text("# Intro", encoding="utf-8")

    result = service.source_hash(config)

    context_file = context_dir / "alumno.md"
    manual_file = manual_dir / "00-intro.md"
    expected_payload = [
        {"path": context_file.resolve().as_posix(), "sha256": hashlib.sha256(context_file.read_bytes()).hexdigest()},
        {"path": manual_file.resolve().as_posix(), "sha256": hashlib.sha256(manual_file.read_bytes()).hexdigest()},
        {"config_sections": [{"id": "intro"}]},
    ]
    expected = hashlib.sha256(
        json.dumps(expected_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert result == expected


def test_source_hash_skips_missing_context_dir_and_defaults_config_sections_to_empty(tmp_path: Path, service):
    config = _config(tmp_path, paths={"context_dir": str(tmp_path / "does-not-exist")})
    # manual_dir exists (from _config) but is empty; only the "config_sections"
    # sentinel entry survives, matching the "no sections in config" default.
    result = service.source_hash(config)
    expected_payload = [{"config_sections": []}]
    expected = hashlib.sha256(
        json.dumps(expected_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert result == expected


def test_prompt_hash_hashes_markdown_files_under_prompts_dir(tmp_path: Path, service):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "section-author.md").write_text("Eres un redactor.", encoding="utf-8")
    config = _config(tmp_path, paths={"prompts_dir": str(prompts_dir)})

    result = service.prompt_hash(config)

    prompt_file = prompts_dir / "section-author.md"
    expected_payload = [{"path": "section-author.md", "sha256": hashlib.sha256(prompt_file.read_bytes()).hexdigest()}]
    expected = hashlib.sha256(
        json.dumps(expected_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert result == expected


def test_prompt_hash_empty_payload_when_prompts_dir_missing(tmp_path: Path, service):
    config = _config(tmp_path, paths={"prompts_dir": str(tmp_path / "missing-prompts")})
    result = service.prompt_hash(config)
    expected = hashlib.sha256(json.dumps([], ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    assert result == expected
