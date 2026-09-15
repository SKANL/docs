from __future__ import annotations

import json

from docs.application.flat_pipeline_v2 import FlatPipelineV2Adapter


def test_flat_pipeline_v2_executes_declared_prep_stages_and_stops_on_fail_fast() -> None:
    calls: list[str] = []

    def operation(name: str, passed: bool = True):
        def run() -> tuple[bool, str]:
            calls.append(name)
            return passed, f"detail:{name}"

        return run

    adapter = FlatPipelineV2Adapter(
        operations={
            "doctor": operation("doctor"),
            "build-rules": operation("build-rules"),
            "review-rules": operation("review-rules", False),
            "collect-sources": operation("collect-sources"),
        },
        clock=lambda: 1.25,
    )

    result = adapter.run("prep", strict=True)

    assert result["passed"] is False
    assert calls == ["doctor", "build-rules", "review-rules"]
    assert result["stages"][-1] == {
        "stage": "review-rules",
        "ok": False,
        "duration_s": 0.0,
        "detail": "detail:review-rules",
    }


def test_flat_pipeline_v2_summary_is_json_serializable() -> None:
    adapter = FlatPipelineV2Adapter(
        operations={"doctor": lambda: (True, "ok")},
        clock=lambda: 4.0,
    )

    result = adapter.run("prep", strict=False)

    json.dumps(result)
    assert result["stage_set"] == "prep"
