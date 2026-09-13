from docs.cli.commands.v2_app import _renderer_capabilities
from docs.domain.tool_capability import ToolCapability, ToolCapabilityRegistry


def test_registry_checks_tools_lazily_and_reports_stable_sorted_capabilities(monkeypatch):
    calls = []

    def which(name):
        calls.append(name)
        return f"/bin/{name}" if name == "pandoc" else None

    monkeypatch.setattr("shutil.which", which)
    registry = ToolCapabilityRegistry([
        ToolCapability(name="zeta", executable="zeta"),
        ToolCapability(name="pandoc", executable="pandoc"),
    ])

    assert calls == []
    assert registry.report() == {
        "pandoc": {"available": True, "path": "/bin/pandoc"},
        "zeta": {"available": False, "path": None},
    }
    assert calls == ["pandoc", "zeta"]
    assert registry.report() == {
        "pandoc": {"available": True, "path": "/bin/pandoc"},
        "zeta": {"available": False, "path": None},
    }
    assert calls == ["pandoc", "zeta"]


def test_capability_report_contains_no_execution_or_plugin_metadata(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    registry = ToolCapabilityRegistry([ToolCapability(name="java", executable="java", required=True)])

    assert registry.report() == {"java": {"available": False, "path": None}}


def test_registry_reports_missing_required_capabilities_without_changing_public_report(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    registry = ToolCapabilityRegistry((
        ToolCapability("pandoc", "pandoc", required=True),
        ToolCapability("soffice", "soffice"),
    ))

    assert registry.missing_required() == ("pandoc",)
    assert registry.report() == {
        "pandoc": {"available": False, "path": None},
        "soffice": {"available": False, "path": None},
    }


def test_registry_merges_duplicate_declarations_and_preserves_requiredness(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    registry = ToolCapabilityRegistry(
        (
            ToolCapability("resvg", "resvg"),
            ToolCapability("resvg", "resvg", required=True),
        )
    )

    assert registry.capabilities == (ToolCapability("resvg", "resvg", required=True),)
    assert registry.missing_required() == ("resvg",)


def test_registry_can_detect_python_module_capabilities_lazily(monkeypatch):
    calls = []

    def find_spec(name):
        calls.append(name)
        return object() if name == "PIL" else None

    monkeypatch.setattr("importlib.util.find_spec", find_spec)
    registry = ToolCapabilityRegistry(
        (ToolCapability("pillow", "", module="PIL"), ToolCapability("pdfium", "", module="pypdfium2"))
    )

    assert calls == []
    assert registry.report() == {
        "pdfium": {"available": False, "path": None},
        "pillow": {"available": True, "path": "python:PIL"},
    }
    assert calls == ["pypdfium2", "PIL"]


def test_renderer_capability_adapter_preserves_module_probe():
    class Renderer:
        required_capabilities = (ToolCapability("pdfium", "", module="pypdfium2"),)

    capabilities = _renderer_capabilities(Renderer())

    assert capabilities[0].module == "pypdfium2"


def test_capability_diagnostics_exposes_policy_metadata_without_changing_report(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "C:/bin/soffice.exe")
    registry = ToolCapabilityRegistry((
        ToolCapability(
            "soffice",
            "soffice",
            required=True,
            requirement="required for PDF release builds",
            degradation="skip PDF in draft mode",
        ),
    ))

    assert registry.report() == {"soffice": {"available": True, "path": "C:/bin/soffice.exe"}}
    assert registry.diagnostics() == {
        "soffice": {
            "available": True,
            "path": "C:/bin/soffice.exe",
            "required": True,
            "kind": "executable",
            "version": None,
            "requirement": "required for PDF release builds",
            "degradation": "skip PDF in draft mode",
        }
    }
