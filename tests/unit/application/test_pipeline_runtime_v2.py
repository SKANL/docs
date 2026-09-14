from pathlib import Path

import pytest

from docs.application.pipeline_runtime_v2 import PipelineRuntime
from docs.application.provenance_v2 import ProvenanceLedgerV2
from docs.domain.pipeline_kernel import ArtifactContract, PipelineDefinition, StageResult, StageSpec
from docs.domain.pipeline_policy import PipelineMode, PipelinePolicy
from docs.domain.tool_capability import ToolCapability, ToolCapabilityRegistry


def test_run_returns_stable_report_and_records_successful_run(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    output = tmp_path / "report.docx"
    source.write_text("source body", encoding="utf-8")
    output.write_bytes(b"rendered bytes")
    ledger = ProvenanceLedgerV2(tmp_path / "provenance-v2.json")

    def render() -> StageResult:
        ledger.record_run("build-001", inputs=(source,), outputs=(output,))
        return StageResult("render", True)

    runtime = PipelineRuntime(
        PipelineDefinition(
            artifacts=(ArtifactContract("report"),),
            stages=(StageSpec("render", produces=("report",)),),
        ),
        {"render": render},
        ToolCapabilityRegistry((ToolCapability("renderer", "missing-renderer"),)),
        ledger,
    )

    report = runtime.run("build-001", inputs=(source,), outputs=(output,))

    assert report.succeeded is True
    assert report.provenance is not None
    assert report.to_json() == (
        '{"capabilities":{"renderer":{"available":false,"path":null}},'
        '"execution":{"results":[{"artifacts":[],"errors":[],"ok":true,'
        '"outcome":"succeeded","stage":"render","warnings":[]}]},'
        '"provenance":{"inputs":{"source.md":'
        '"8e0217a3ecb3eea361aa1807153c7ad853ff9e4d3e107a2d8be40ad66ceb2dc6"},'
        '"outputs":{"report.docx":'
        '"03cde4e27f36b5bd6fc62afa5ef10863f23b1deb96a9753f29b2e473a382c739"},'
        '"run_id":"build-001"},"succeeded":true}'
    )
    assert ProvenanceLedgerV2(tmp_path / "provenance-v2.json").load_run("build-001") == report.provenance


def test_run_does_not_record_provenance_when_a_stage_fails(tmp_path: Path) -> None:
    ledger = ProvenanceLedgerV2(tmp_path / "provenance-v2.json")
    runtime = PipelineRuntime(
        PipelineDefinition(stages=(StageSpec("render"),)),
        {"render": lambda: StageResult("render", False, errors=("render failed",))},
        ToolCapabilityRegistry(()),
        ledger,
    )

    report = runtime.run("build-001")

    assert report.succeeded is False
    assert report.provenance is None
    assert report.to_json() == (
        '{"capabilities":{},"execution":{"results":[{"artifacts":[],"errors":'
        '["render failed"],"ok":false,"outcome":"failed","stage":"render","warnings":[]}]},'
        '"provenance":null,"succeeded":false}'
    )
    assert ledger.load_run("build-001") is None


def test_draft_policy_blocks_publish(tmp_path: Path) -> None:
    runtime = PipelineRuntime(
        PipelineDefinition(
            artifacts=(ArtifactContract("report"),),
            stages=(StageSpec("publish", produces=("report",)),),
        ),
        {"publish": lambda: StageResult("publish", True, warnings=("visual.blank",))},
        ToolCapabilityRegistry(()),
        ProvenanceLedgerV2(tmp_path / "provenance-v2.json"),
        PipelinePolicy(PipelineMode.draft),
    )

    report = runtime.run("release-001")

    assert report.succeeded is False
    assert report.provenance is None
    assert any("publish disallowed" in error for result in report.execution.results for error in result.errors)


def test_strict_missing_required_capability_stops_before_handlers(tmp_path: Path) -> None:
    calls: list[str] = []
    runtime = PipelineRuntime(
        PipelineDefinition(stages=(StageSpec("render"),)),
        {"render": lambda: (calls.append("render") or StageResult("render", True))},
        ToolCapabilityRegistry((ToolCapability("pandoc", "definitely-missing", required=True),)),
        ProvenanceLedgerV2(tmp_path / "provenance-v2.json"),
        PipelinePolicy(PipelineMode.strict),
    )

    report = runtime.run("build-missing-tool")

    assert calls == []
    assert report.succeeded is False
    assert report.execution.results[0].errors == ("required capability unavailable: pandoc",)


def test_release_missing_required_capability_stops_before_handlers(tmp_path: Path) -> None:
    calls: list[str] = []
    runtime = PipelineRuntime(
        PipelineDefinition(stages=(StageSpec("render"),)),
        {"render": lambda: (calls.append("render") or StageResult("render", True))},
        ToolCapabilityRegistry((ToolCapability("pandoc", "definitely-missing", required=True),)),
        ProvenanceLedgerV2(tmp_path / "provenance-v2.json"),
        PipelinePolicy(PipelineMode.release),
    )

    report = runtime.run("release-missing-tool")

    assert calls == []
    assert report.succeeded is False
    assert report.execution.results[0].errors == ("required capability unavailable: pandoc",)


def test_draft_missing_required_capability_is_degraded_to_warning(tmp_path: Path) -> None:
    runtime = PipelineRuntime(
        PipelineDefinition(stages=(StageSpec("render"),)),
        {"render": lambda: StageResult("render", True)},
        ToolCapabilityRegistry((ToolCapability("pandoc", "definitely-missing", required=True),)),
        ProvenanceLedgerV2(tmp_path / "provenance-v2.json"),
        PipelinePolicy(PipelineMode.draft),
    )

    report = runtime.run("draft-missing-tool", excluded_stages={"publish"})

    assert report.succeeded is True
    assert report.execution.results[0].warnings == ("required capability unavailable: pandoc",)


def test_draft_missing_required_capability_cannot_publish_outputs(tmp_path: Path) -> None:
    calls: list[str] = []
    runtime = PipelineRuntime(
        PipelineDefinition(
            artifacts=(ArtifactContract("rendered"),),
            stages=(
                StageSpec("render", produces=("rendered",)),
                StageSpec("publish-draft", requires=("rendered",)),
            ),
        ),
        {
            "render": lambda: (calls.append("render") or StageResult("render", True)),
            "publish-draft": lambda: (calls.append("publish") or StageResult("publish-draft", True)),
        },
        ToolCapabilityRegistry((ToolCapability("pandoc", "definitely-missing", required=True),)),
        ProvenanceLedgerV2(tmp_path / "provenance-v2.json"),
        PipelinePolicy(PipelineMode.draft),
    )

    report = runtime.run("draft-missing-tool-publish", outputs=(tmp_path / "report.docx",))

    assert calls == ["render"]
    assert report.succeeded is False
    assert any(
        "required capability unavailable: pandoc" in error
        for result in report.execution.results
        for error in result.errors
    )


def test_policy_promoted_warning_stops_before_publish_handler(tmp_path: Path) -> None:
    calls: list[str] = []
    runtime = PipelineRuntime(
        PipelineDefinition(
            artifacts=(ArtifactContract("verified"),),
            stages=(StageSpec("verify", produces=("verified",)), StageSpec("publish", requires=("verified",))),
        ),
        {
            "verify": lambda: (calls.append("verify") or StageResult("verify", True, warnings=("visual.blank",))),
            "publish": lambda: (calls.append("publish") or StageResult("publish", True)),
        },
        ToolCapabilityRegistry(()),
        ProvenanceLedgerV2(tmp_path / "provenance-v2.json"),
        PipelinePolicy(PipelineMode.strict),
    )

    report = runtime.run("build-warning")

    assert calls == ["verify"]
    assert report.succeeded is False
    assert report.execution.results[0].errors == ("visual.blank",)


def test_draft_policy_blocks_publish_draft_stage(tmp_path: Path) -> None:
    calls: list[str] = []
    runtime = PipelineRuntime(
        PipelineDefinition(stages=(StageSpec("publish-draft"),)),
        {"publish-draft": lambda: (calls.append("publish") or StageResult("publish-draft", True))},
        ToolCapabilityRegistry(()),
        ProvenanceLedgerV2(tmp_path / "provenance-v2.json"),
        PipelinePolicy(PipelineMode.draft),
    )

    report = runtime.run("draft-publish")

    assert calls == []
    assert report.succeeded is False
    assert any("publish disallowed" in error for result in report.execution.results for error in result.errors)


def test_draft_policy_allows_unsupported_optional_stage_and_continues(tmp_path: Path) -> None:
    calls: list[str] = []
    runtime = PipelineRuntime(
        PipelineDefinition(artifacts=(ArtifactContract("optional-output"),), stages=(StageSpec("optional", produces=("optional-output",), optional=True), StageSpec("later", requires=("optional-output",)))),
        {"later": lambda: (calls.append("later") or StageResult("later", True))},
        ToolCapabilityRegistry(()),
        ProvenanceLedgerV2(tmp_path / "provenance-v2.json"),
        PipelinePolicy(PipelineMode.draft),
    )

    report = runtime.run("draft-optional-failure", excluded_stages={"publish-draft"})

    assert calls == ["later"]
    assert report.succeeded is True
    assert report.execution.results[0].outcome == "unsupported"


def test_strict_policy_keeps_optional_stage_failure_blocking(tmp_path: Path) -> None:
    runtime = PipelineRuntime(
        PipelineDefinition(stages=(StageSpec("optional", optional=True),)),
        {"optional": lambda: StageResult("optional", False, errors=("offline",))},
        ToolCapabilityRegistry(()),
        ProvenanceLedgerV2(tmp_path / "provenance-v2.json"),
        PipelinePolicy(PipelineMode.strict),
    )

    report = runtime.run("strict-optional-failure")

    assert report.succeeded is False
    assert report.execution.results[0].errors == ("offline",)


def test_strict_and_release_package_failure_blocks_publish_draft(tmp_path: Path) -> None:
    for mode in (PipelineMode.strict, PipelineMode.release):
        calls: list[str] = []
        runtime = PipelineRuntime(
                PipelineDefinition(
                    artifacts=(ArtifactContract("package-release-complete"),),
                    stages=(
                        StageSpec("package-release", produces=("package-release-complete",), optional=True),
                        StageSpec("publish-draft", requires=("package-release-complete",)),
                ),
            ),
            {
                "package-release": lambda calls=calls: (calls.append("package") or StageResult("package-release", False, errors=("package unavailable",))),
                "publish-draft": lambda calls=calls: (calls.append("publish") or StageResult("publish-draft", True)),
            },
            ToolCapabilityRegistry(()),
            ProvenanceLedgerV2(tmp_path / f"{mode.value}-provenance.json"),
            PipelinePolicy(mode),
        )

        report = runtime.run(f"{mode.value}-package-failure", outputs=(tmp_path / f"{mode.value}.txt",))

        assert calls == ["package"]
        assert report.succeeded is False
        assert any(
            result.stage == "publish-draft" and "package-release" in " ".join(result.errors)
            for result in report.execution.results
        )


@pytest.mark.parametrize("outcome", ("unsupported", "skipped"))
@pytest.mark.parametrize("mode", (PipelineMode.strict, PipelineMode.release))
def test_strict_and_release_package_gap_cannot_permit_publication(
    tmp_path: Path, outcome: str, mode: PipelineMode
) -> None:
    calls: list[str] = []

    def package_release() -> StageResult:
        calls.append("package")
        return getattr(StageResult, outcome)("package-release")

    runtime = PipelineRuntime(
        PipelineDefinition(
            artifacts=(ArtifactContract("package-release-complete"),),
            stages=(
                StageSpec("package-release", produces=("package-release-complete",), optional=True),
                StageSpec("publish-draft", requires=("package-release-complete",)),
            ),
        ),
        {
            "package-release": package_release,
            "publish-draft": lambda: (calls.append("publish") or StageResult("publish-draft", True)),
        },
        ToolCapabilityRegistry(()),
        ProvenanceLedgerV2(tmp_path / f"{mode.value}-{outcome}.json"),
        PipelinePolicy(mode),
    )

    report = runtime.run(f"{mode.value}-{outcome}", outputs=(tmp_path / "published.txt",))

    assert calls == ["package"]
    assert report.succeeded is False
    assert any(
        result.stage == "publish-draft" and result.ok is False
        for result in report.execution.results
    )


def test_required_unsupported_stage_blocks_publication_before_publish_handler(tmp_path: Path) -> None:
    calls: list[str] = []
    runtime = PipelineRuntime(
        PipelineDefinition(
            artifacts=(ArtifactContract("required-output"),),
            stages=(
                StageSpec("required-gap", produces=("required-output",)),
                StageSpec("publish-draft", requires=("required-output",)),
            ),
        ),
        {"publish-draft": lambda: (calls.append("publish") or StageResult("publish-draft", True))},
        ToolCapabilityRegistry(()),
        ProvenanceLedgerV2(tmp_path / "provenance-v2.json"),
    )

    report = runtime.run("required-gap", outputs=(tmp_path / "published.txt",))

    assert calls == []
    assert report.succeeded is False
    assert report.execution.results[0].errors == ("stage unsupported: required-gap",)


def test_runtime_does_not_create_late_provenance_after_success(tmp_path: Path) -> None:
    ledger = ProvenanceLedgerV2(tmp_path / "provenance-v2.json")
    output = tmp_path / "output.txt"
    output.write_text("output", encoding="utf-8")
    runtime = PipelineRuntime(
        PipelineDefinition(stages=(StageSpec("render"),)),
        {"render": lambda: StageResult("render", True)},
        ToolCapabilityRegistry(()),
        ledger,
    )

    report = runtime.run("no-late-write", outputs=(output,))

    assert report.succeeded is True
    assert report.provenance is None
    assert ledger.load_run("no-late-write") is None


def test_runtime_preserves_authoritative_provenance_recorded_by_stage(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    output = tmp_path / "report.docx"
    source.write_text("source", encoding="utf-8")
    output.write_text("output", encoding="utf-8")
    ledger = ProvenanceLedgerV2(tmp_path / "provenance-v2.json")

    def record() -> StageResult:
        ledger.record_run("authoritative", inputs=(source,), outputs=(output,))
        return StageResult("record", True)

    runtime = PipelineRuntime(
        PipelineDefinition(stages=(StageSpec("record"),)),
        {"record": record},
        ToolCapabilityRegistry(()),
        ledger,
    )

    report = runtime.run("authoritative")

    assert report.provenance == ledger.load_run("authoritative")
    assert report.provenance == {
        "run_id": "authoritative",
        "inputs": {"source.md": "".join(__import__("hashlib").sha256(b"source").hexdigest())},
        "outputs": {"report.docx": __import__("hashlib").sha256(b"output").hexdigest()},
    }
