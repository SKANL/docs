from __future__ import annotations

from pathlib import Path
from typing import Any

from docs.application.legacy_pipeline import LegacyPipelineService


def test_run_pipeline_delegates_without_changing_arguments_or_result() -> None:
    calls: list[tuple[Any, ...]] = []
    expected = {"passed": True, "stages": []}

    class Pipeline:
        def run_pipeline(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            calls.append((args, kwargs))
            return expected

    service = LegacyPipelineService(Pipeline())
    template = object()
    config = {"paths": {"runs_dir": "runs"}}
    result = service.run_pipeline("doc", template, config, "assemble", Path("repo"), strict=True, renderer="renderer")

    assert result is expected
    assert calls == [(("doc", template, config, "assemble", Path("repo")), {"strict": True, "renderer": "renderer"})]
