from pathlib import Path

from docs.domain.models.template import Template

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "templates"


def _load(name: str) -> Template:
    return Template.from_json((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def test_parses_sections_and_contracts():
    template = _load("reporte-estadia-tic")
    ids = {s.id for s in template.sections}
    assert "introduccion" in ids
    assert template.section_contracts["resumen"].required_content


def test_parses_context_schema_topics_and_fields():
    template = _load("reporte-estadia-tic")
    alumno = next(t for t in template.context_schema.topics if t.id == "alumno")
    assert alumno.required is True
    assert any(f.key == "nombre" and f.required for f in alumno.fields)
    assert "introduccion" in alumno.consumed_by


def test_both_templates_load():
    assert _load("reporte-estadia-tic").type == "reporte-estadia-tic"
    assert _load("documento-generico").type == "documento-generico"
