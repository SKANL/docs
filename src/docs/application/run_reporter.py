"""Stable reporting for ordered pipeline stage results."""

from __future__ import annotations

from collections.abc import Iterable

from docs.application.pipeline_executor import PipelineReport
from docs.domain.pipeline_kernel import StageResult


class RunReporter:
    """Create the existing stable execution report from stage results."""

    def report(self, results: Iterable[StageResult]) -> PipelineReport:
        return PipelineReport(tuple(results))
