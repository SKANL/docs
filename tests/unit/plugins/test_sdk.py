from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import Any, cast

import pytest

from docs.plugins.manifest import ManifestError, generate_sbom, manifest_hash, manifest_identity, validate_manifest
from docs.plugins.runner import PluginRunError, PluginRunner, SandboxAttestation


def manifest(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema": "docs.plugin/v1",
        "id": "example.renderer",
        "version": "1.2.0",
        "entrypoint": [sys.executable, "-c", "import json; print(json.dumps({'ok': True}))"],
        "capabilities": ["render"],
    }
    value.update(overrides)
    return value


def sandbox_runner(
    *, timeout_seconds: float = 10.0, max_output_bytes: int = 1_048_576, max_scratch_files: int = 1_000
) -> PluginRunner:
    return PluginRunner(
        sandbox_provider=_TestSandboxProvider(),
        timeout_seconds=timeout_seconds,
        max_output_bytes=max_output_bytes,
        max_scratch_files=max_scratch_files,
    )


class _TestSandboxProvider:
    def attest(self, requested: frozenset[str]) -> SandboxAttestation:
        return SandboxAttestation("test-boundary", requested)

    def command(self, entrypoint: tuple[str, ...]) -> tuple[str, ...]:
        return entrypoint

    def verify_filesystem_isolation(self, scratch_root: Path) -> bool:
        return scratch_root.is_dir()


class _AttestationOnlySandboxProvider:
    def attest(self, requested: frozenset[str]) -> SandboxAttestation:
        return SandboxAttestation("test-boundary", requested)

    def command(self, entrypoint: tuple[str, ...]) -> tuple[str, ...]:
        return entrypoint


def test_validates_manifest_and_hash_is_stable_for_mapping_order() -> None:
    validated = validate_manifest(manifest())
    reordered = {key: manifest()[key] for key in reversed(list(manifest()))}

    assert validated.plugin_id == "example.renderer"
    assert manifest_hash(manifest()) == manifest_hash(reordered)


def test_legacy_manifest_defaults_to_safe_contract() -> None:
    validated = validate_manifest(manifest())
    assert validated.api == "docs.plugin/v1"
    assert validated.permissions == frozenset({"read_input", "write_scratch"})
    assert validated.network is False
    assert validated.deterministic is True


def test_plan_fields_and_metadata_are_validated() -> None:
    validated = validate_manifest(manifest(
        api="docs.plugin/v1", formats=["document.docx"], permissions=["read_input"],
        resource_limits={"timeout_seconds": 1, "output_bytes": 1000, "scratch_bytes": 1000, "scratch_files": 2},
        signature={"algorithm": "ed25519", "key_id": "publisher-1", "value": "abc"},
        toolchain={"runtime": "python-3.11"},
    ))
    assert validated.formats == ("document.docx",)
    assert validated.signature["algorithm"] == "ed25519"
    assert manifest_identity(validated)


def test_rejects_unsafe_permission_signature_and_nested_fields() -> None:
    with pytest.raises(ManifestError, match="unsafe permission"):
        validate_manifest(manifest(permissions=["read_input", "publish"]))
    with pytest.raises(ManifestError, match="unsafe"):
        validate_manifest(manifest(signature={"algorithm": "none", "key_id": "x", "value": "y"}))
    with pytest.raises(ManifestError, match="unknown resource_limits field"):
        validate_manifest(manifest(resource_limits={"network": True}))


def test_manifest_limits_must_fit_runner_before_spawn() -> None:
    runner = sandbox_runner(timeout_seconds=1, max_output_bytes=100, max_scratch_files=2)
    with pytest.raises(PluginRunError, match="exceeds runner limit"):
        runner.run(validate_manifest(manifest(resource_limits={"output_bytes": 101})), {})


def test_sbom_is_deterministic_and_does_not_execute_entrypoint() -> None:
    first = generate_sbom(validate_manifest(manifest(toolchain={"runtime": "python-3.11"})))
    second = generate_sbom(validate_manifest(manifest(toolchain={"runtime": "python-3.11"})))
    assert first == second
    assert first["format"] == "docs.sbom/v1"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("schema", "docs.plugin/v2", "schema"),
        ("id", "../escape", "id"),
        ("entrypoint", ["python", "-c", ""], "entrypoint"),
        ("capabilities", ["network"], "network"),
        ("unexpected", True, "unknown manifest field"),
    ],
)
def test_rejects_unsafe_or_malformed_manifest(field: str, value: object, message: str) -> None:
    with pytest.raises(ManifestError, match=message):
        validate_manifest(manifest(**{field: value}))


def test_runner_returns_json_and_does_not_write_to_publication_directory(tmp_path) -> None:
    command = [sys.executable, "-c", "import json; print(json.dumps({'echo': json.load(__import__('sys').stdin)}))"]
    result = sandbox_runner(timeout_seconds=2, max_output_bytes=1024).run(
        validate_manifest(manifest(entrypoint=command)), {"title": "Draft"}, publication_dir=tmp_path
    )

    assert result.output == {"echo": {"title": "Draft"}}
    assert result.output_hash == manifest_hash(result.output)
    assert list(tmp_path.iterdir()) == []


def test_runner_times_out_and_kills_child() -> None:
    command = [sys.executable, "-c", "import time; time.sleep(10)"]

    started = time.monotonic()
    with pytest.raises(PluginRunError, match="timed out"):
        sandbox_runner(timeout_seconds=0.05, max_output_bytes=1024).run(
            validate_manifest(manifest(entrypoint=command)), {}
        )

    assert time.monotonic() - started < 2


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object cleanup regression")
def test_runner_times_out_while_plugin_never_reads_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    command = [sys.executable, "-c", "import time; time.sleep(10)"]
    payload = {"data": "x" * (2 * 1024 * 1024)}
    real_run = subprocess.run

    def delayed_taskkill(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        if args and args[0][0] == "taskkill":
            time.sleep(1.05)
        return real_run(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", delayed_taskkill)

    started = time.monotonic()
    with pytest.raises(PluginRunError, match="timed out"):
        sandbox_runner(timeout_seconds=0.05, max_output_bytes=1024).run(
            validate_manifest(manifest(entrypoint=command)), payload
        )

    assert time.monotonic() - started < 1


def test_runner_rejects_output_over_limit() -> None:
    command = [sys.executable, "-c", "print('x' * 100)"]

    with pytest.raises(PluginRunError, match="output limit"):
        sandbox_runner(timeout_seconds=2, max_output_bytes=16).run(
            validate_manifest(manifest(entrypoint=command)), {}
        )


def test_runner_uses_sanitized_environment_and_explicit_roots() -> None:
    command = [
        sys.executable,
        "-c",
        (
            "import json, os; "
            "print(json.dumps({'env': sorted(os.environ), "
            "'input': os.environ['DOCS_PLUGIN_INPUT_ROOT'], "
            "'scratch': os.environ['DOCS_PLUGIN_SCRATCH_ROOT']}))"
        ),
    ]

    result = sandbox_runner(timeout_seconds=2, max_output_bytes=4096).run(
        validate_manifest(manifest(entrypoint=command)), {}
    )

    assert result.output["env"] == [
        "DOCS_PLUGIN_INPUT_ROOT",
        "DOCS_PLUGIN_NETWORK",
        "DOCS_PLUGIN_SCRATCH_ROOT",
        "PATH",
        "PYTHONIOENCODING",
    ]
    assert result.output["input"] != result.output["scratch"]


def test_runner_joins_readers_before_deciding_output_size() -> None:
    command = [sys.executable, "-c", "import sys; sys.stdout.write('x' * 128); sys.stdout.flush()"]

    with pytest.raises(PluginRunError, match="output limit"):
        sandbox_runner(timeout_seconds=2, max_output_bytes=16).run(
            validate_manifest(manifest(entrypoint=command)), {}
        )


@pytest.mark.parametrize("payload", [object(), float("nan")])
def test_runner_converts_payload_serialization_errors(payload: object) -> None:
    with pytest.raises(PluginRunError, match="JSON serialization"):
        sandbox_runner(timeout_seconds=2, max_output_bytes=1024).run(
            validate_manifest(manifest()), payload
        )


def test_runner_timeout_terminates_descendant_process(tmp_path) -> None:
    child_pid = tmp_path / "child.pid"
    child_survived = tmp_path / "child-survived"
    command = [
        sys.executable,
        "-c",
        (
            "import subprocess, sys, time; "
            f"child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
            f"open({str(child_pid)!r}, 'w').write(str(child.pid)); time.sleep(1); open({str(child_survived)!r}, 'w').write('yes')"
        ),
    ]

    with pytest.raises(PluginRunError, match="timed out"):
        sandbox_runner(timeout_seconds=0.75, max_output_bytes=1024).run(
            validate_manifest(manifest(entrypoint=command)), {}
        )

    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and not child_pid.exists():
        time.sleep(0.01)
    assert child_pid.exists()
    time.sleep(1.2)
    assert not child_survived.exists()


def test_runner_fails_closed_when_requested_isolation_is_unavailable() -> None:
    with pytest.raises(PluginRunError, match="requested isolation cannot be enforced"):
        PluginRunner(requested_isolation={"network"}).run(validate_manifest(manifest()), {})


def test_runner_allows_unsandboxed_execution_only_for_digest_bound_credential() -> None:
    raw = manifest(id="builtin.renderer")
    digest = manifest_identity(validate_manifest(raw))
    result = PluginRunner(
        requested_isolation={"network", "filesystem"},
        allow_unsandboxed=True,
        trusted_credentials={digest: "builtin-token"},
    ).run(validate_manifest(raw), {}, trusted_token="builtin-token")

    assert result.metadata["isolation"] == {
        "requested": ["filesystem", "network"],
        "enforced": [],
        "unsandboxed": True,
    }


def test_runner_rejects_unsandboxed_opt_in_for_untrusted_plugin() -> None:
    with pytest.raises(PluginRunError, match="manifest-bound trusted credential"):
        PluginRunner(
            requested_isolation={"network"},
            allow_unsandboxed=True,
            trusted_credentials={"wrong-digest": "builtin-token"},
        ).run(validate_manifest(manifest(id="builtin.renderer")), {}, trusted_token="wrong-token")


def test_runner_does_not_treat_manifest_id_as_trusted_identity() -> None:
    with pytest.raises(PluginRunError, match="manifest-bound trusted credential"):
        PluginRunner(
            requested_isolation={"network"},
            allow_unsandboxed=True,
            trusted_builtin_ids={"builtin.renderer"},
        ).run(validate_manifest(manifest(id="builtin.renderer")), {})


def test_runner_enforces_measurable_scratch_limits_and_reports_usage() -> None:
    command = [
        sys.executable,
        "-c",
        "from pathlib import Path; Path('one').write_text('1234'); Path('two').write_text('5678'); import json; print(json.dumps({'ok': True}))",
    ]

    with pytest.raises(PluginRunError, match="scratch file limit exceeded"):
        sandbox_runner(timeout_seconds=2, max_output_bytes=1024, max_scratch_files=1).run(
            validate_manifest(manifest(entrypoint=command)), {}
        )

    result = sandbox_runner(timeout_seconds=2, max_output_bytes=1024, max_scratch_files=3).run(
        validate_manifest(manifest(entrypoint=command)), {}
    )
    scratch = cast(dict[str, Any], result.metadata["scratch"])
    assert scratch["file_limit"] == 3
    assert scratch["files_used"] == 2
    assert scratch["bytes_used"] == 8


def test_runner_reports_scratch_scan_failure_instead_of_ignoring_oserror(monkeypatch) -> None:
    def fail_scan(_root, _pattern):
        raise OSError("scan failed")

    monkeypatch.setattr("pathlib.Path.rglob", fail_scan)

    with pytest.raises(PluginRunError, match="scratch usage could not be determined"):
        PluginRunner()._scratch_usage(Path("."))


def test_runner_rejects_untrusted_execution_without_os_sandbox() -> None:
    with pytest.raises(PluginRunError, match="sandbox"):
        PluginRunner().run(validate_manifest(manifest()), {})


def test_runner_does_not_accept_legacy_sandbox_claims_as_attestation() -> None:
    with pytest.raises(PluginRunError, match="sandbox"):
        PluginRunner(sandbox_launcher=lambda command: command, sandbox_available=True).run(
            validate_manifest(manifest()), {}
        )


def test_runner_rejects_sandbox_without_independent_filesystem_verifier() -> None:
    with pytest.raises(PluginRunError, match="filesystem isolation"):
        PluginRunner(sandbox_provider=_AttestationOnlySandboxProvider()).run(
            validate_manifest(manifest()), {}
        )


def test_runner_trust_digest_includes_entrypoint() -> None:
    raw = manifest(id="builtin.renderer")
    digest = manifest_identity(validate_manifest(raw))
    changed = validate_manifest(manifest(id="builtin.renderer", entrypoint=[sys.executable, "-c", "print('{}')"]))
    with pytest.raises(PluginRunError, match="manifest-bound trusted credential"):
        PluginRunner(allow_unsandboxed=True, trusted_credentials={digest: "token"}).run(changed, {}, trusted_token="token")


def test_runner_trust_credential_binds_complete_manifest_identity() -> None:
    original = validate_manifest(manifest(id="builtin.renderer"))
    changed = validate_manifest(manifest(id="builtin.renderer", permissions=["read_input"]))

    with pytest.raises(PluginRunError, match="manifest-bound trusted credential"):
        PluginRunner(
            allow_unsandboxed=True,
            trusted_credentials={manifest_identity(original): "token"},
        ).run(changed, {}, trusted_token="token")


def test_runner_bounds_and_redacts_plugin_stderr() -> None:
    command = [sys.executable, "-c", "import sys; sys.stderr.write('token=secret ' * 1000); sys.exit(1)"]
    with pytest.raises(PluginRunError) as error:
        sandbox_runner(timeout_seconds=2, max_output_bytes=128).run(
            validate_manifest(manifest(entrypoint=command)), {}
        )
    assert "secret" not in str(error.value)
    assert len(str(error.value)) < 300


def test_runner_rejects_non_finite_plugin_json() -> None:
    command = [sys.executable, "-c", "print('{\"value\": NaN}')"]
    with pytest.raises(PluginRunError, match="finite JSON"):
        sandbox_runner(timeout_seconds=2, max_output_bytes=1024).run(
            validate_manifest(manifest(entrypoint=command)), {}
        )
