# tests/unit/application/test_context_gap_report.py
"""Unit coverage for ContextService.build_gap_report (design.md Decision 7,
spec: document-pipeline "Machine-Readable Gap Report"). Uses the same
lightweight fakes as test_context_service.py -- exercises the NEW
combination of context-required-field gaps (reusing status/missing_fields)
and section required_content gaps (reusing rules.requirement_present) in
isolation, distinct from the pipeline-level draft/strict wiring covered by
tests/integration/test_pipeline_strict_gap.py."""
from __future__ import annotations

import json
from pathlib import Path

from docs.application.context import ContextService
from docs.domain.models.template import ContextSchema, Field, SectionContract, Template, Topic


class _FakeDocumentRepo:
    def exists(self, doc_id: str) -> bool:
        return True


class _FakeContextRepo:
    def __init__(self, values: dict[str, object] | None = None) -> None:
        self.values: dict[str, object] = values or {}

    def topic_exists(self, doc_id: str, topic_id: str) -> bool:
        return topic_id in self.values

    def read_topic(self, doc_id: str, topic: Topic):
        return self.values.get(topic.id, {})


def _template(topic: Topic, section_contracts: dict[str, SectionContract] | None = None) -> Template:
    return Template(
        type="doc", title="Doc",
        context_schema=ContextSchema(topics=[topic]),
        section_contracts=section_contracts or {},
    )


def test_missing_required_context_field_appears_as_a_context_gap(tmp_path: Path):
    topic = Topic(
        id="alumno", title="Alumno", required=True,
        fields=[Field(key="nombre", label="Nombre", required=True)],
    )
    template = _template(topic)
    service = ContextService(_FakeContextRepo(), _FakeDocumentRepo(), context_markdown=None)

    report = service.build_gap_report("doc1", template, section_bodies={}, sections_dir=tmp_path)

    assert report["context_gaps"] == [{"topic_id": "alumno", "missing": ["Nombre"]}]


def test_missing_section_required_content_appears_as_a_section_gap(tmp_path: Path):
    topic = Topic(id="alumno", title="Alumno", required=False)
    contracts = {"introduccion": SectionContract(required_content=["objetivo", "alcance"])}
    template = _template(topic, contracts)
    service = ContextService(_FakeContextRepo(), _FakeDocumentRepo(), context_markdown=None)

    report = service.build_gap_report(
        "doc1", template,
        section_bodies={"introduccion": "Este texto solo menciona el objetivo del proyecto."},
        sections_dir=tmp_path,
    )

    assert report["section_gaps"] == [{"section_id": "introduccion", "missing": ["alcance"]}]


def test_freshly_scaffolded_unedited_section_reports_every_required_item_as_a_gap(tmp_path: Path):
    # CRITICAL-1 (verify-report-pr6.md): driven by the REAL
    # render_contract_scaffold() output -- not hand-typed text -- so this
    # would have caught the scaffold self-matching bug directly.
    from docs.domain.section_rendering import render_contract_scaffold

    topic = Topic(id="alumno", title="Alumno", required=False)
    contract = SectionContract(required_content=["objetivo del proyecto", "justificacion", "problema"])
    contracts = {"introduccion": contract}
    template = _template(topic, contracts)
    service = ContextService(_FakeContextRepo(), _FakeDocumentRepo(), context_markdown=None)
    scaffold_body = render_contract_scaffold("Introducción", contract, context={})

    report = service.build_gap_report(
        "doc1", template,
        section_bodies={"introduccion": scaffold_body},
        sections_dir=tmp_path,
    )

    assert report["section_gaps"] == [
        {"section_id": "introduccion", "missing": ["objetivo del proyecto", "justificacion", "problema"]}
    ]


def test_gap_report_is_empty_when_context_and_sections_are_complete(tmp_path: Path):
    topic = Topic(
        id="alumno", title="Alumno", required=True,
        fields=[Field(key="nombre", label="Nombre", required=True)],
    )
    contracts = {"introduccion": SectionContract(required_content=["objetivo"])}
    template = _template(topic, contracts)
    service = ContextService(
        _FakeContextRepo({"alumno": {"nombre": "Ada"}}), _FakeDocumentRepo(), context_markdown=None
    )

    report = service.build_gap_report(
        "doc1", template,
        section_bodies={"introduccion": "El objetivo de este documento es..."},
        sections_dir=tmp_path,
    )

    assert report == {"schema": 1, "context_gaps": [], "section_gaps": []}


def test_gap_report_is_written_atomically_as_deterministic_json(tmp_path: Path):
    topic = Topic(id="alumno", title="Alumno", required=False)
    template = _template(topic)
    service = ContextService(_FakeContextRepo(), _FakeDocumentRepo(), context_markdown=None)

    report = service.build_gap_report("doc1", template, section_bodies={}, sections_dir=tmp_path)

    written = json.loads((tmp_path / "gap-report.json").read_text(encoding="utf-8"))
    assert written == report
    assert b"generated_at" not in (tmp_path / "gap-report.json").read_bytes()
