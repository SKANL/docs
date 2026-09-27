from __future__ import annotations

from docs.application.run_reporter import RunReporter
from docs.domain.pipeline_kernel import StageResult


def test_run_reporter_preserves_ordered_stage_results_in_a_stable_report() -> None:
    report = RunReporter().report(
        (StageResult("render", True), StageResult("publish", False, errors=("blocked",)))
    )

    assert report.to_json() == (
        '{"results":[{"artifacts":[],"errors":[],"ok":true,"outcome":"succeeded",'
        '"stage":"render","warnings":[]},{"artifacts":[],"errors":["blocked"],'
        '"ok":false,"outcome":"failed","stage":"publish","warnings":[]}]}'
    )
