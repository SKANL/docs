# tests/unit/domain/test_rules_characterization.py
"""Characterization net for the policy-de-hardcoding front (universal-schema-harness).

These tests snapshot the CURRENT behavior of `review_rules`/`review_section_text`
for the `reporte-estadia-tic` fixture, captured before any `rules.py`/`normative.py`
edit. Every later task in this front (conditional check conversions, normative
literal evacuation) MUST reproduce these snapshots byte-for-byte — a diff here
means a real behavior regression for the estadía document type, not an
acceptable refactor side effect.
"""

from __future__ import annotations

import json
from pathlib import Path

from docs.domain.evidence import build_manifest
from docs.domain.models.template import Template
from docs.domain.normative import resolve_normative_settings
from docs.domain.rules import review_rules, review_section_text

_FIXTURE = (
    Path(__file__).resolve().parents[2] / "fixtures" / "templates" / "reporte-estadia-tic.json"
)


def _load_raw() -> dict:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _load_template() -> Template:
    return Template.model_validate(_load_raw())


def test_review_rules_reporte_estadia_tic_draft_manifest_present_is_clean():
    template = _load_template()
    result = review_rules(template, manifest_exists=True, manifest_size=42, strict=False)
    assert [issue.to_dict() for issue in result.issues] == []
    assert result.passed is True


def test_build_manifest_policy_block_reporte_estadia_tic_snapshot():
    # Extended scope (fresh-context verify, PR1 fix batch, CRITICAL-1): the
    # original characterization net (task 1.1) covered only
    # review_rules/review_section_text, so a real regression in build_manifest's
    # "policy" block (normative_source silently dropping to "") slipped through
    # undetected. This snapshot pins the FULL policy block, driven by the real
    # fixture's own declared values (not synthetic hand-picked params) via the
    # same resolution expressions `application/evidence.py` uses.
    raw = _load_raw()
    manifest = build_manifest(
        manual_files=[],
        traceability=[],
        advisor_overrides=raw.get("advisor_overrides", []),
        draft_mode=raw.get("strict_policy", {}).get("draft", {}),
        strict_mode=raw.get("strict_policy", {}).get("strict", {}),
        preliminaries=raw.get("preliminaries", {}),
        format=raw.get("format", {}),
        apa7=raw.get("apa7", {}),
        privacy=raw.get("privacy", {}),
        section_contracts={},
        contract_hashes={},
        normative_source=raw.get("normative", {}).get("normative_source", ""),
        pdf_and_extracted_use=raw.get("paths", {}).get("extracted_dir_policy", ""),
    )
    assert manifest["policy"] == {
        "normative_source": "docs/guides/manual-estadia-tic",
        "pdf_and_extracted_use": "rules_traceability_only",
        "apa_style": "APA 7",
        "advisor_overrides": raw["advisor_overrides"],
        "draft_mode": raw["strict_policy"]["draft"],
        "strict_mode": raw["strict_policy"]["strict"],
    }


def test_review_rules_reporte_estadia_tic_strict_manifest_absent_snapshot():
    template = _load_template()
    result = review_rules(template, manifest_exists=False, manifest_size=0, strict=True)
    assert [issue.to_dict() for issue in result.issues] == [
        {
            "severity": "error",
            "message": "No existe manual-rules.json; ejecuta `build-rules`.",
            "code": "",
        }
    ]
    assert result.passed is False


# Representative estadía section corpus: exercises first-person/subjective/secret
# detection, missing title, contract length/required-content/evidence gaps, APA
# citation-reference reciprocity, and results-without-evidence -- the full set of
# checks `review_section_text` performs today.
_CORPUS: dict[str, str] = {
    "introduccion": (
        "Yo considero que este proyecto fue excelente y sin duda un éxito total.\n"
        "Los resultados obtenidos fueron positivos.\n"
        "PASSWORD=SuperSecreta123456\n"
    ),
    "resumen": (
        "# RESUMEN\n\nEste resumen no menciona nada de lo requerido en el contrato.\n"
    ),
    "capitulo-ii-marco-teorico": (
        "# CAPÍTULO II. MARCO TEÓRICO\n\n"
        "Se sostiene (García, 2020) sin lista de referencias.\n"
    ),
    "referencias": (
        "# REFERENCIAS BIBLIOGRÁFICAS\n\n"
        "García, A. (2020). Un título largo cualquiera. Editorial.\n"
    ),
}

_EXPECTED_SECTION_ISSUES: dict[str, dict[str, list[dict[str, str]]]] = {
    "introduccion": {
        "draft": [
            {
                "severity": "error",
                "message": "Contiene primera persona o voz no permitida: patrón `\\byo\\b`.",
                "code": "voice.first_person",
            },
            {
                "severity": "error",
                "message": "Contiene primera persona o voz no permitida: patrón `\\bconsidero\\b`.",
                "code": "voice.first_person",
            },
            {
                "severity": "warning",
                "message": "Contiene término subjetivo sin evidencia automática: `excelente`.",
                "code": "voice.subjective_term",
            },
            {
                "severity": "warning",
                "message": "Contiene término subjetivo sin evidencia automática: `éxito`.",
                "code": "voice.subjective_term",
            },
            {
                "severity": "error",
                "message": (
                    "Contiene posible secreto, credencial o dato sensible: patrón "
                    "`\\bpassword\\s*[:=]\\s*['\\\"]?[^'\\\"\\s]{8,}`."
                ),
                "code": "privacy.sensitive_data",
            },
            {
                "severity": "error",
                "message": "La sección no tiene título principal Markdown.",
                "code": "structure.missing_title",
            },
            {
                "severity": "warning",
                "message": "La sección `introduccion` tiene 20 palabras; mínimo esperado: 900.",
                "code": "contract.length_below_min",
            },
            {
                "severity": "warning",
                "message": (
                    "No se detecta contenido obligatorio de `introduccion`: objetivo, "
                    "justificación, problema, delimitación espacial, delimitación "
                    "temporal, unidad de análisis, sustento técnico, método o "
                    "procedimiento, capitulado."
                ),
                "code": "contract.missing_required",
            },
            {
                "severity": "warning",
                "message": "`introduccion` requiere evidencia o marcador PENDIENTE.",
                "code": "evidence.required",
            },
            {
                "severity": "warning",
                "message": "Menciona resultados sin evidencia detectable ni marcador PENDIENTE.",
                "code": "evidence.results_without_evidence",
            },
        ],
        "strict": [
            {
                "severity": "error",
                "message": "Contiene primera persona o voz no permitida: patrón `\\byo\\b`.",
                "code": "voice.first_person",
            },
            {
                "severity": "error",
                "message": "Contiene primera persona o voz no permitida: patrón `\\bconsidero\\b`.",
                "code": "voice.first_person",
            },
            {
                "severity": "warning",
                "message": "Contiene término subjetivo sin evidencia automática: `excelente`.",
                "code": "voice.subjective_term",
            },
            {
                "severity": "warning",
                "message": "Contiene término subjetivo sin evidencia automática: `éxito`.",
                "code": "voice.subjective_term",
            },
            {
                "severity": "error",
                "message": (
                    "Contiene posible secreto, credencial o dato sensible: patrón "
                    "`\\bpassword\\s*[:=]\\s*['\\\"]?[^'\\\"\\s]{8,}`."
                ),
                "code": "privacy.sensitive_data",
            },
            {
                "severity": "error",
                "message": "La sección no tiene título principal Markdown.",
                "code": "structure.missing_title",
            },
            {
                "severity": "error",
                "message": "La sección `introduccion` tiene 20 palabras; mínimo esperado: 900.",
                "code": "contract.length_below_min",
            },
            {
                "severity": "error",
                "message": (
                    "No se detecta contenido obligatorio de `introduccion`: objetivo, "
                    "justificación, problema, delimitación espacial, delimitación "
                    "temporal, unidad de análisis, sustento técnico, método o "
                    "procedimiento, capitulado."
                ),
                "code": "contract.missing_required",
            },
            {
                "severity": "error",
                "message": "`introduccion` requiere evidencia o marcador PENDIENTE.",
                "code": "evidence.required",
            },
            {
                "severity": "warning",
                "message": "Menciona resultados sin evidencia detectable ni marcador PENDIENTE.",
                "code": "evidence.results_without_evidence",
            },
        ],
    },
    "resumen": {
        "draft": [
            {
                "severity": "warning",
                "message": "La sección `resumen` tiene 12 palabras; mínimo esperado: 220.",
                "code": "contract.length_below_min",
            },
            {
                "severity": "warning",
                "message": (
                    "No se detecta contenido obligatorio de `resumen`: tema del "
                    "proyecto, enfoque del trabajo, motivo del proyecto, resultados "
                    "importantes o PENDIENTE."
                ),
                "code": "contract.missing_required",
            },
            {
                "severity": "warning",
                "message": "`resumen` requiere evidencia o marcador PENDIENTE.",
                "code": "evidence.required",
            },
        ],
        "strict": [
            {
                "severity": "error",
                "message": "La sección `resumen` tiene 12 palabras; mínimo esperado: 220.",
                "code": "contract.length_below_min",
            },
            {
                "severity": "error",
                "message": (
                    "No se detecta contenido obligatorio de `resumen`: tema del "
                    "proyecto, enfoque del trabajo, motivo del proyecto, resultados "
                    "importantes o PENDIENTE."
                ),
                "code": "contract.missing_required",
            },
            {
                "severity": "error",
                "message": "`resumen` requiere evidencia o marcador PENDIENTE.",
                "code": "evidence.required",
            },
        ],
    },
    "capitulo-ii-marco-teorico": {
        "draft": [
            {
                "severity": "warning",
                "message": (
                    "No se detecta contenido obligatorio de "
                    "`capitulo-ii-marco-teorico`: fundamentación teórica, enfoque "
                    "deductivo, autores, teorías, conceptos clave, antecedentes."
                ),
                "code": "contract.missing_required",
            },
            {
                "severity": "warning",
                "message": "`capitulo-ii-marco-teorico` requiere evidencia o marcador PENDIENTE.",
                "code": "evidence.required",
            },
            {
                "severity": "warning",
                "message": "Hay citas APA en texto pero no hay lista de referencias detectable.",
                "code": "apa.no_reference_list",
            },
            {
                "severity": "warning",
                "message": "Cita sin referencia correspondiente: `García, 2020`.",
                "code": "apa.citation_without_reference",
            },
        ],
        "strict": [
            {
                "severity": "error",
                "message": (
                    "No se detecta contenido obligatorio de "
                    "`capitulo-ii-marco-teorico`: fundamentación teórica, enfoque "
                    "deductivo, autores, teorías, conceptos clave, antecedentes."
                ),
                "code": "contract.missing_required",
            },
            {
                "severity": "error",
                "message": "`capitulo-ii-marco-teorico` requiere evidencia o marcador PENDIENTE.",
                "code": "evidence.required",
            },
            {
                "severity": "error",
                "message": "Hay citas APA en texto pero no hay lista de referencias detectable.",
                "code": "apa.no_reference_list",
            },
            {
                "severity": "error",
                "message": "Cita sin referencia correspondiente: `García, 2020`.",
                "code": "apa.citation_without_reference",
            },
        ],
    },
    "referencias": {
        "draft": [
            {
                "severity": "warning",
                "message": (
                    "No se detecta contenido obligatorio de `referencias`: formato "
                    "APA 7, orden alfabético."
                ),
                "code": "contract.missing_required",
            },
            {
                "severity": "warning",
                "message": "`referencias` requiere citas APA 7 o marcador PENDIENTE.",
                "code": "apa.required",
            },
            {
                "severity": "warning",
                "message": (
                    "Referencia sin cita correspondiente: `García, A. (2020). Un "
                    "título largo cualquiera. Editorial.`."
                ),
                "code": "apa.reference_without_citation",
            },
        ],
        "strict": [
            {
                "severity": "error",
                "message": (
                    "No se detecta contenido obligatorio de `referencias`: formato "
                    "APA 7, orden alfabético."
                ),
                "code": "contract.missing_required",
            },
            {
                "severity": "error",
                "message": "`referencias` requiere citas APA 7 o marcador PENDIENTE.",
                "code": "apa.required",
            },
            {
                "severity": "error",
                "message": (
                    "Referencia sin cita correspondiente: `García, A. (2020). Un "
                    "título largo cualquiera. Editorial.`."
                ),
                "code": "apa.reference_without_citation",
            },
        ],
    },
}


def test_review_section_text_reporte_estadia_tic_corpus_snapshot():
    template = _load_template()
    normative = resolve_normative_settings(_load_raw())

    for section_id, text in _CORPUS.items():
        contract = template.section_contracts.get(section_id)
        for strict, key in ((False, "draft"), (True, "strict")):
            issues = review_section_text(
                text, {}, section_id, contract, template, strict, normative=normative
            )
            actual = [issue.to_dict() for issue in issues]
            expected = _EXPECTED_SECTION_ISSUES[section_id][key]
            assert actual == expected, f"{section_id} ({key}) drifted from characterization snapshot"
