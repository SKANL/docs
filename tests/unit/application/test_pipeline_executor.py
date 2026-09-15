from docs.application.pipeline_executor import PipelineExecutor
from docs.domain.pipeline_kernel import ArtifactContract, ArtifactRecord, PipelineDefinition, StageResult, StageSpec


def test_executes_in_definition_plan_and_reports_results_deterministically():
    definition = PipelineDefinition(
        artifacts=(ArtifactContract("a"), ArtifactContract("b")),
        stages=(
            StageSpec("second", requires=("a",), produces=("b",)),
            StageSpec("first", produces=("a",)),
        ),
    )
    calls = []
    handlers = {
        "first": lambda: (calls.append("first") or StageResult("first", True)),
        "second": lambda: (calls.append("second") or StageResult("second", True)),
    }

    report = PipelineExecutor(definition, handlers).run()

    assert calls == ["first", "second"]
    assert [result.stage for result in report.results] == ["first", "second"]
    assert report.to_json() == '{"results":[{"artifacts":[],"errors":[],"ok":true,"outcome":"succeeded","stage":"first","warnings":[]},{"artifacts":[],"errors":[],"ok":true,"outcome":"succeeded","stage":"second","warnings":[]}]}'


def test_fail_fast_failure_stops_unconnected_stages():
    definition = PipelineDefinition(stages=(StageSpec("fail"), StageSpec("later")))
    calls = []
    handlers = {
        "fail": lambda: (calls.append("fail") or StageResult("fail", False, errors=("boom",))),
        "later": lambda: (calls.append("later") or StageResult("later", True)),
    }

    report = PipelineExecutor(definition, handlers).run()

    assert calls == ["fail"]
    assert report.results[0].errors == ("boom",)
    assert len(report.results) == 1


def test_connected_fail_fast_failure_stops_independent_stages():
    definition = PipelineDefinition(
        artifacts=(ArtifactContract("built"),),
        stages=(StageSpec("build", produces=("built",)), StageSpec("later")),
    )
    calls: list[str] = []

    report = PipelineExecutor(
        definition,
        {
            "build": lambda: (calls.append("build") or StageResult("build", False, errors=("boom",))),
            "later": lambda: (calls.append("later") or StageResult("later", True)),
        },
    ).run()

    assert calls == ["build"]
    assert [result.stage for result in report.results] == ["build"]


def test_connected_fail_fast_failure_records_blocked_dependents_without_running_unrelated_stages():
    definition = PipelineDefinition(
        artifacts=(ArtifactContract("built"),),
        stages=(
            StageSpec("build", produces=("built",)),
            StageSpec("dependent", requires=("built",)),
            StageSpec("unrelated"),
        ),
    )
    calls: list[str] = []

    report = PipelineExecutor(
        definition,
        {
            "build": lambda: (calls.append("build") or StageResult("build", False, errors=("boom",))),
            "dependent": lambda: (calls.append("dependent") or StageResult("dependent", True)),
            "unrelated": lambda: (calls.append("unrelated") or StageResult("unrelated", True)),
        },
    ).run()

    assert calls == ["build"]
    assert [result.stage for result in report.results] == ["build", "dependent"]
    assert report.results[-1].errors == ("required dependency unavailable: built",)


def test_failure_blocks_dependents_but_does_not_stop_independent_stages():
    definition = PipelineDefinition(
        artifacts=(ArtifactContract("built"),),
        stages=(
            StageSpec("build", produces=("built",), fail_fast=False),
            StageSpec("dependent", requires=("built",)),
            StageSpec("independent"),
        ),
    )
    calls: list[str] = []

    report = PipelineExecutor(
        definition,
        {
            "build": lambda: (calls.append("build") or StageResult("build", False, errors=("boom",))),
            "dependent": lambda: (calls.append("dependent") or StageResult("dependent", True)),
            "independent": lambda: (calls.append("independent") or StageResult("independent", True)),
        },
    ).run()

    assert calls == ["build", "independent"]
    assert [result.stage for result in report.results] == ["build", "dependent", "independent"]
    assert report.results[1].errors == ("required dependency unavailable: built",)


def test_executor_rejects_missing_external_prerequisite_before_running_handlers():
    definition = PipelineDefinition(
        artifacts=(ArtifactContract("context"),),
        stages=(StageSpec("build", requires=("context",)),),
        external_artifacts=frozenset({"context"}),
    )
    calls: list[str] = []

    report = PipelineExecutor(
        definition,
        {"build": lambda: (calls.append("build") or StageResult("build", True))},
    ).run()

    assert calls == []
    assert report.results[0].errors == ("required external artifact unavailable: context",)


def test_executor_records_non_negative_stage_duration():
    definition = PipelineDefinition(stages=(StageSpec("render"),))
    report = PipelineExecutor(definition, {"render": lambda: StageResult("render", True)}).run()

    assert report.results[0].duration_ms is not None
    assert report.results[0].duration_ms >= 0


def test_failed_producer_does_not_execute_dependent_stage_even_when_not_fail_fast():
    definition = PipelineDefinition(artifacts=(ArtifactContract("optional-output"),), stages=(StageSpec("optional", produces=("optional-output",), fail_fast=False), StageSpec("later", requires=("optional-output",))))
    calls = []
    handlers = {
        "optional": lambda: (calls.append("optional") or StageResult("optional", False, errors=("skip",))),
        "later": lambda: (calls.append("later") or StageResult("later", True)),
    }

    report = PipelineExecutor(definition, handlers).run()

    assert calls == ["optional"]
    assert [result.stage for result in report.results] == ["optional", "later"]
    assert report.results[-1].ok is False
    assert report.results[-1].errors == ("required dependency unavailable: optional-output",)


def test_unsupported_stage_result_is_deterministic_and_keeps_pipeline_running_in_draft():
    definition = PipelineDefinition(
        artifacts=(ArtifactContract("migration-output"), ArtifactContract("output")),
        stages=(
            StageSpec("migration-gap", produces=("migration-output",), optional=True),
            StageSpec("legacy", requires=("migration-output",), produces=("output",)),
        ),
    )
    calls = []
    handlers = {
        "legacy": lambda: (calls.append("legacy") or StageResult("legacy", True)),
    }

    report = PipelineExecutor(definition, handlers).run()

    assert calls == ["legacy"]
    assert report.results[0].outcome == "unsupported"
    assert report.results[0].warnings == ("stage unsupported: migration-gap",)
    assert report.to_json() == (
        '{"results":[{"artifacts":[],"errors":[],"ok":true,"outcome":"unsupported",'
        '"stage":"migration-gap","warnings":["stage unsupported: migration-gap"]},'
        '{"artifacts":[],"errors":[],"ok":true,"outcome":"succeeded",'
        '"stage":"legacy","warnings":[]}]}'
    )


def test_excluded_stage_with_produced_artifact_blocks_downstream_stage():
    definition = PipelineDefinition(
        artifacts=(ArtifactContract("draft"), ArtifactContract("verified")),
        stages=(
            StageSpec("build", produces=("draft",)),
            StageSpec("verify", requires=("draft",), produces=("verified",)),
        ),
    )
    calls: list[str] = []

    report = PipelineExecutor(
        definition,
        {"verify": lambda: (calls.append("verify") or StageResult("verify", True))},
    ).run(excluded_stages={"build"})

    assert calls == []
    assert len(report.results) == 1
    assert report.results[0].stage == "verify"
    assert report.results[0].ok is False
    assert report.results[0].errors == ("required dependency unavailable: draft",)


def test_handler_exception_is_reported_as_failed_stage_result():
    definition = PipelineDefinition(stages=(StageSpec("explode"), StageSpec("later")))

    report = PipelineExecutor(
        definition,
        {
            "explode": lambda: (_ for _ in ()).throw(RuntimeError("boom")),
            "later": lambda: StageResult("later", True),
        },
    ).run()

    assert [result.stage for result in report.results] == ["explode"]
    assert report.results[0].ok is False
    assert report.results[0].errors == ("stage handler failed: boom",)


def test_required_dependency_skip_is_reported_as_blocking_result():
    definition = PipelineDefinition(
        artifacts=(ArtifactContract("built"), ArtifactContract("checked")),
        stages=(
            StageSpec("build", produces=("built",), fail_fast=False),
            StageSpec("check", requires=("built",), produces=("checked",)),
        ),
    )
    report = PipelineExecutor(
        definition,
        {"build": lambda: StageResult("build", False, errors=("broken",))},
    ).run()

    assert [result.stage for result in report.results] == ["build", "check"]
    assert report.results[-1].ok is False
    assert report.results[-1].errors == ("required dependency unavailable: built",)


def test_unsupported_optional_stage_blocks_a_required_output_dependency():
    definition = PipelineDefinition(
        artifacts=(ArtifactContract("generated", required=True), ArtifactContract("published")),
        stages=(
            StageSpec("optional-render", produces=("generated",), optional=True),
            StageSpec("publish", requires=("generated",), produces=("published",)),
        ),
    )
    report = PipelineExecutor(definition, {}).run()
    assert report.results[0].outcome == "unsupported"
    assert report.results[1].errors == ("required dependency unavailable: generated",)


def test_stage_report_rejects_artifacts_outside_declared_outputs():
    definition = PipelineDefinition(
        artifacts=(ArtifactContract("rendered"), ArtifactContract("other")),
        stages=(StageSpec("render", produces=("rendered",)),),
    )

    report = PipelineExecutor(
        definition,
        {"render": lambda: StageResult("render", True, artifacts=(
            ArtifactRecord(
                "other", "other.bin", "abc"
            ),
        ))},
    ).run()

    assert report.results[0].ok is False
    assert report.results[0].errors == ("undeclared artifact produced: other",)


def test_stage_report_rejects_a_required_artifact_record_with_the_wrong_identity():
    definition = PipelineDefinition(
        artifacts=(ArtifactContract("rendered", required=True, media_type="text/plain"),),
        stages=(StageSpec("render", produces=("rendered",)),),
    )

    report = PipelineExecutor(
        definition,
        {"render": lambda: StageResult("render", True, artifacts=(
            ArtifactRecord(
                "rendered", "report.txt", "0" * 64, media_type="application/json", size_bytes=1
            ),
        ))},
    ).run()

    assert report.results[0].ok is False
    assert report.results[0].errors == (
        "artifact rendered does not satisfy its contract: media_type must be text/plain",
    )


def test_stage_report_rejects_missing_media_metadata_for_explicit_media_contract():
    definition = PipelineDefinition(
        artifacts=(ArtifactContract("rendered", required=True, media_type="text/plain"),),
        stages=(StageSpec("render", produces=("rendered",)),),
    )

    report = PipelineExecutor(
        definition,
        {"render": lambda: StageResult("render", True, artifacts=(
            ArtifactRecord("rendered", "report.txt", "0" * 64),
        ))},
    ).run()

    assert report.results[0].ok is False
    assert report.results[0].errors == (
        "artifact rendered does not satisfy its contract: media_type is required",
    )


def test_stage_report_preserves_compact_records_for_implicit_media_contracts():
    definition = PipelineDefinition(
        artifacts=(ArtifactContract("rendered"),),
        stages=(StageSpec("render", produces=("rendered",)),),
    )

    report = PipelineExecutor(
        definition,
        {"render": lambda: StageResult("render", True, artifacts=(
            ArtifactRecord("rendered", "report.txt", "abc"),
        ))},
    ).run()

    assert report.results[0].ok is True


def test_stage_report_rejects_short_digest_for_explicit_strict_contracts():
    definition = PipelineDefinition(
        artifacts=(ArtifactContract("rendered", require_full_sha256=True),),
        stages=(StageSpec("render", produces=("rendered",)),),
    )

    report = PipelineExecutor(
        definition,
        {"render": lambda: StageResult("render", True, artifacts=(
            ArtifactRecord("rendered", "report.txt", "abc"),
        ))},
    ).run()

    assert report.results[0].ok is False
    assert report.results[0].errors == (
        "artifact rendered does not satisfy its contract: sha256 must be a SHA-256 digest",
    )


def test_failed_optional_stage_with_fail_fast_does_not_stop_required_unrelated_stage():
    definition = PipelineDefinition(
        stages=(StageSpec("optional", optional=True, fail_fast=True), StageSpec("required"))
    )
    calls = []
    report = PipelineExecutor(definition, {
        "optional": lambda: (calls.append("optional") or StageResult("optional", False, errors=("degraded",))),
        "required": lambda: (calls.append("required") or StageResult("required", True)),
    }).run()

    assert calls == ["optional", "required"]
    assert report.results[-1].ok is True


def test_failed_optional_producer_blocks_only_its_downstream_consumers():
    definition = PipelineDefinition(
        artifacts=(ArtifactContract("optional-output"), ArtifactContract("published")),
        stages=(
            StageSpec("optional", produces=("optional-output",), optional=True, fail_fast=True),
            StageSpec("consumer", requires=("optional-output",)),
            StageSpec("unrelated", produces=("published",)),
        ),
    )
    calls: list[str] = []

    report = PipelineExecutor(
        definition,
        {
            "optional": lambda: (
                calls.append("optional") or StageResult("optional", False, errors=("degraded",))
            ),
            "consumer": lambda: (calls.append("consumer") or StageResult("consumer", True)),
            "unrelated": lambda: (calls.append("unrelated") or StageResult("unrelated", True)),
        },
    ).run()

    assert calls == ["optional", "unrelated"]
    assert report.results[1].errors == ("required dependency unavailable: optional-output",)
    assert report.results[2].ok is True


def test_missing_required_declared_output_fails_producer_and_blocks_consumer():
    definition = PipelineDefinition(
        artifacts=(
            ArtifactContract("built", required=True),
            ArtifactContract("published"),
        ),
        stages=(
            StageSpec("build", produces=("built",), fail_fast=False),
            StageSpec("publish", requires=("built",), produces=("published",)),
        ),
    )
    calls: list[str] = []

    report = PipelineExecutor(
        definition,
        {
            "build": lambda: (calls.append("build") or StageResult("build", True)),
            "publish": lambda: (calls.append("publish") or StageResult("publish", True)),
        },
    ).run()

    assert calls == ["build"]
    assert report.results[0].stage == "build"
    assert report.results[0].ok is False
    assert report.results[0].errors == ("required declared artifact missing: built",)
    assert report.results[1].stage == "publish"
    assert report.results[1].ok is False
    assert report.results[1].errors == ("required dependency unavailable: built",)


def test_excluded_stage_blocks_explicit_after_dependent_without_artifact_requirement():
    definition = PipelineDefinition(
        stages=(
            StageSpec("prepare"),
            StageSpec("after-prepare", after=("prepare",)),
            StageSpec("independent"),
        )
    )
    calls: list[str] = []

    report = PipelineExecutor(
        definition,
        {
            "prepare": lambda: (calls.append("prepare") or StageResult("prepare", True)),
            "after-prepare": lambda: (calls.append("after-prepare") or StageResult("after-prepare", True)),
            "independent": lambda: (calls.append("independent") or StageResult("independent", True)),
        },
    ).run(excluded_stages={"prepare"})

    assert calls == ["independent"]
    assert [result.stage for result in report.results] == ["independent", "after-prepare"]
    assert report.results[1].errors == ("required dependency unavailable: prepare",)


def test_executor_preserves_durable_contract_records_in_stage_reports() -> None:
    record = ArtifactRecord(
        "prepared",
        "stages/prepare/prepared.json",
        "0" * 64,
        producer_stage="prepare",
    )
    definition = PipelineDefinition(
        artifacts=(ArtifactContract("prepared", require_full_sha256=True),),
        stages=(StageSpec("prepare", produces=("prepared",)),),
    )

    report = PipelineExecutor(
        definition,
        {"prepare": lambda: StageResult("prepare", True, artifacts=(record,))},
    ).run()

    assert report.results[0].artifacts == (record,)


