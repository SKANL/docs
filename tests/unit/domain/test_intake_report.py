# tests/unit/domain/test_intake_report.py
from docs.domain.intake_report import render_intake_report


def _detection(files):
    return {
        "processed": len(files),
        "files": files,
        "ignored": [],
        "media_cleanup": {"removed": [], "refused": []},
    }


def _manifest(sources, conflicts=None):
    return {"schema": 1, "sources": sources, "duplicates": [], "placements": [], "conflicts": conflicts or []}


def test_render_intake_report_lists_found_sources_with_role_and_status():
    detection = _detection([{"relative_path": "proyecto.md", "kind": "markdown", "status": "ingested"}])
    manifest = _manifest(
        [
            {
                "relative_path": "proyecto.md",
                "proposed_role": "requirements",
                "confidence": "high",
                "role_status": {"effective_role": "requirements", "blocked": False, "gap": None},
            }
        ]
    )

    report = render_intake_report(detection, manifest, {}, [])

    assert "## Encontrado" in report
    assert "`proyecto.md` (markdown, rol: requirements, confianza: high) -- ingested" in report


def test_render_intake_report_no_sources_says_so():
    report = render_intake_report(_detection([]), _manifest([]), {}, [])

    assert "No se encontraron fuentes en `inbox/`." in report


def test_render_intake_report_lists_context_and_section_gaps_under_missing():
    gap_report = {
        "context_gaps": [{"topic_id": "objetivo", "missing": ["descripcion"]}],
        "section_gaps": [{"section_id": "introduccion", "missing": ["problema"]}],
    }

    report = render_intake_report(_detection([]), _manifest([]), gap_report, [])

    assert "### Contexto sin completar" in report
    assert "`objetivo`: descripcion" in report
    assert "### Secciones con contenido obligatorio faltante" in report
    assert "`introduccion`: problema" in report


def test_render_intake_report_lists_pending_classifications():
    manifest = _manifest(
        [
            {
                "relative_path": "guia.pdf",
                "proposed_role": "manual",
                "confidence": "low",
                "role_status": {
                    "effective_role": None,
                    "blocked": True,
                    "gap": "Rol retenido (confianza low, propuesto: manual).",
                },
            }
        ]
    )

    report = render_intake_report(_detection([]), manifest, {}, [])

    assert "### Clasificaciones sin confirmar" in report
    assert "`guia.pdf`" in report


def test_render_intake_report_lists_conflicts_as_warn():
    manifest = _manifest(
        [], conflicts=[{"group": "backend_runtime", "members": ["node", "php"], "sources": ["a.md", "b.md"]}]
    )

    report = render_intake_report(_detection([]), manifest, {}, [])

    assert "### Conflictos entre fuentes (WARN)" in report
    assert "backend_runtime" in report
    assert "`a.md`" in report and "`b.md`" in report


def test_render_intake_report_lists_ledger_pending_lines():
    report = render_intake_report(_detection([]), _manifest([]), {}, ["PENDIENTE: horas totales"])

    assert "### Ledger pendiente" in report
    assert "PENDIENTE: horas totales" in report


def test_render_intake_report_how_to_finish_checklist_orders_and_numbers_steps():
    manifest = _manifest(
        [
            {
                "relative_path": "guia.pdf",
                "proposed_role": "manual",
                "confidence": "low",
                "role_status": {"effective_role": None, "blocked": True, "gap": "Rol retenido."},
            }
        ]
    )
    gap_report = {"context_gaps": [{"topic_id": "objetivo", "missing": ["descripcion"]}]}

    report = render_intake_report(_detection([]), manifest, gap_report, ["PENDIENTE: algo"])

    checklist_section = report.split("## Cómo terminar")[1]
    assert "1. Confirmar el rol de `guia.pdf`" in checklist_section
    assert "2. Completar el contexto `objetivo`" in checklist_section
    assert "3. Resolver en el ledger: PENDIENTE: algo" in checklist_section


def test_render_intake_report_no_gaps_says_all_clear():
    report = render_intake_report(_detection([]), _manifest([]), {}, [])

    assert "No se detectaron brechas." in report
    assert "No quedan pasos pendientes." in report
