"""The inline CLI logic of build-ledger, review-rules and doctor, now owned by the application layer."""

from pathlib import Path
from types import SimpleNamespace

from docs.application.document_tools import check_rules, run_diagnostics, write_fact_ledger
from docs.domain.doctor import Check, DoctorResult


def test_write_fact_ledger_renders_confirmed_context_into_the_configured_path(tmp_path):
    target = tmp_path / "nested" / "ledger.md"
    seen = {}

    class Context:
        def confirmed_lines(self, doc_id, template):
            seen["args"] = (doc_id, template)
            return ["a confirmed fact"]

    class Evidence:
        def render_fact_ledger(self, config, lines):
            seen["lines"] = lines
            return "# Fact Ledger\n"

    deps = SimpleNamespace(context=Context(), evidence=Evidence())
    resolved = SimpleNamespace(doc_id="d", template="T", config={"paths": {"fact_ledger": str(target)}})
    assert write_fact_ledger(deps, resolved) == target
    assert target.read_text(encoding="utf-8") == "# Fact Ledger\n"
    assert seen == {"args": ("d", "T"), "lines": ["a confirmed fact"]}


def test_check_rules_reads_the_manifest_state_and_applies_strictness():
    from docs.domain.models.template import Template

    template = Template.model_validate({"type": "t", "title": "T", "sections": [], "section_contracts": {},
                                        "context_schema": {"topics": []}})
    states = []
    deps = SimpleNamespace(rules_manifest_state=lambda config: states.append(config) or (False, 0))
    resolved = SimpleNamespace(template=template, config={"paths": {}})
    loose, strict = check_rules(deps, resolved, strict=False), check_rules(deps, resolved, strict=True)
    assert states == [{"paths": {}}, {"paths": {}}]
    assert isinstance(loose.passed, bool) and isinstance(strict.passed, bool)


def test_run_diagnostics_attaches_sorted_capabilities(tmp_path):
    class Registry:
        def report(self):
            return {"b": {"ok": True}, "a": {"ok": False}}

        def diagnostics(self):
            return {"z": {"ok": True}, "y": {"ok": True}}

    calls = []
    deps = SimpleNamespace(
        doctor=SimpleNamespace(run_doctor=lambda doc_id, config, strict=False: DoctorResult([Check("python", True, "x")])),
        resolve_renderer=lambda config: "renderer",
        create_capability_registry=lambda renderer, fmt, root, paths: calls.append((renderer, fmt, root, paths)) or Registry(),
        workspace=SimpleNamespace(doc_root=lambda doc_id: tmp_path / doc_id),
    )
    resolved = SimpleNamespace(doc_id="d", config={"output": {"format": "html"}, "paths": {"p": 1}})
    result = run_diagnostics(deps, resolved, strict=True)
    assert list(result.capabilities) == ["a", "b"] and list(result.capability_diagnostics) == ["y", "z"]
    assert calls == [("renderer", "html", tmp_path / "d", {"p": 1})]


def test_run_diagnostics_tolerates_an_unresolvable_renderer(tmp_path):
    seen = []
    deps = SimpleNamespace(
        doctor=SimpleNamespace(run_doctor=lambda *a, **k: DoctorResult([])),
        resolve_renderer=lambda config: (_ for _ in ()).throw(ValueError("no renderer")),
        create_capability_registry=lambda renderer, *rest: seen.append(renderer) or SimpleNamespace(
            report=lambda: {}, diagnostics=lambda: {}),
        workspace=SimpleNamespace(doc_root=lambda doc_id: Path(tmp_path)),
    )
    run_diagnostics(deps, SimpleNamespace(doc_id="d", config={}), strict=False)
    assert seen == [None]
