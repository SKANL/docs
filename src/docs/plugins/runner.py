from __future__ import annotations

import ctypes
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from docs.domain.evidence_passport import redact
from docs.plugins.manifest import PluginManifest, generate_sbom, manifest_hash, manifest_identity, plugin_identity


class PluginRunError(RuntimeError):
    """Raised when an isolated plugin process cannot produce a valid result."""

    def __init__(self, message: str, *, metadata: Mapping[str, object] | None = None) -> None:
        super().__init__(message)
        self.metadata = dict(metadata or {})


@dataclass(frozen=True)
class PluginRunResult:
    output: Any
    output_hash: str
    stdout: str
    metadata: Mapping[str, object]
    plugin_identity: str = ""
    manifest_digest: str = ""
    toolchain: Mapping[str, str] = None  # type: ignore[assignment]
    sbom: Mapping[str, object] = None  # type: ignore[assignment]


@dataclass(frozen=True)
class SandboxAttestation:
    provider: str
    enforced_modes: frozenset[str]


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _THREADENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_uint32),
        ("cntUsage", ctypes.c_uint32),
        ("th32ThreadID", ctypes.c_uint32),
        ("th32OwnerProcessID", ctypes.c_uint32),
        ("tpBasePri", ctypes.c_int32),
        ("tpDeltaPri", ctypes.c_int32),
        ("dwFlags", ctypes.c_uint32),
    ]


@dataclass(frozen=True)
class _WindowsJobObject:
    api: Any
    handle: Any


class PlatformSandboxProvider(Protocol):
    """OS-backed sandbox boundary; its attestation is not caller metadata."""

    def attest(self, requested: frozenset[str]) -> SandboxAttestation: ...

    def command(self, entrypoint: tuple[str, ...]) -> tuple[str, ...]: ...

    def verify_filesystem_isolation(self, scratch_root: Path) -> bool: ...


class PluginRunner:
    """Run plugins with explicit limits and honest OS isolation metadata."""

    _ISOLATION_MODES = frozenset({"network", "filesystem"})
    _MAX_ERROR_TEXT = 256
    _CLEANUP_SUBPROCESS_TIMEOUT_SECONDS = 0.1

    def __init__(
        self,
        *,
        timeout_seconds: float = 10.0,
        max_output_bytes: int = 1_048_576,
        requested_isolation: Iterable[str] = (),
        allow_unsandboxed: bool = False,
        trusted_builtin_ids: Iterable[str] = (),
        trusted_builtin_tokens: Iterable[str] = (),
        trusted_credentials: Mapping[str, str] | None = None,
        sandbox_provider: PlatformSandboxProvider | None = None,
        sandbox_launcher: Callable[[tuple[str, ...]], tuple[str, ...]] | None = None,
        sandbox_available: bool = False,
        max_scratch_bytes: int = 64 * 1024 * 1024,
        max_scratch_files: int = 1_000,
    ) -> None:
        requested = frozenset(requested_isolation)
        if requested - self._ISOLATION_MODES:
            raise ValueError("unsupported isolation mode requested")
        if timeout_seconds <= 0 or max_output_bytes <= 0:
            raise ValueError("timeout and output limits must be positive")
        if max_scratch_bytes <= 0 or max_scratch_files <= 0:
            raise ValueError("scratch limits must be positive")
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes
        self.requested_isolation = requested
        self.allow_unsandboxed = allow_unsandboxed
        self.trusted_builtin_ids = frozenset(trusted_builtin_ids)
        self.trusted_builtin_tokens = frozenset(trusted_builtin_tokens)
        self.trusted_credentials = dict(trusted_credentials or {})
        # The legacy knobs are retained for callers, but are deliberately not
        # security inputs. Only a provider-issued platform attestation counts.
        del sandbox_launcher, sandbox_available
        self.sandbox_provider = sandbox_provider
        self.max_scratch_bytes = max_scratch_bytes
        self.max_scratch_files = max_scratch_files

    def run(
        self,
        manifest: PluginManifest,
        payload: Any,
        publication_dir: Path | None = None,
        *,
        trusted_token: str | None = None,
        artifact_digest: str | None = None,
    ) -> PluginRunResult:
        """Run a plugin with stdin/stdout only; never hand it a publication path."""
        del publication_dir
        metadata: dict[str, object] = {
            "isolation": {"requested": sorted(self.requested_isolation), "enforced": [], "unsandboxed": False},
            "scratch": {"byte_limit": self.max_scratch_bytes, "file_limit": self.max_scratch_files, "bytes_used": 0, "files_used": 0},
        }
        self._validate_manifest_contract(manifest)
        identity = plugin_identity(manifest, artifact_digest)
        metadata.update({"plugin_identity": identity, "manifest_digest": manifest_identity(manifest)})
        trusted = trusted_token is not None and self.trusted_credentials.get(identity) == trusted_token
        if self.allow_unsandboxed and not trusted:
            raise PluginRunError("allow_unsandboxed requires a manifest-bound trusted credential", metadata=metadata)
        attestation: SandboxAttestation | None = None
        if not self.allow_unsandboxed:
            # Network denial is a sandbox responsibility, even when the
            # manifest does not request network. The environment variable is
            # informational only and is never treated as enforcement.
            sandbox_requested = self.requested_isolation | frozenset({"network", "filesystem"})
            attestation = self._sandbox_attestation(sandbox_requested)
            if sandbox_requested:
                if attestation is None or not sandbox_requested <= attestation.enforced_modes:
                    raise PluginRunError("requested isolation cannot be enforced by sandbox", metadata=metadata)
            elif attestation is None:
                raise PluginRunError("untrusted plugin requires an OS-enforced sandbox", metadata=metadata)
        metadata["isolation"] = {
            "requested": sorted(self.requested_isolation),
            "enforced": sorted(self.requested_isolation & attestation.enforced_modes) if attestation is not None else [],
            "unsandboxed": bool(self.allow_unsandboxed),
        }
        try:
            encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
        except (TypeError, ValueError) as exc:
            raise PluginRunError("plugin JSON serialization failed", metadata=metadata) from exc

        try:
            with tempfile.TemporaryDirectory(prefix="docs-plugin-") as workdir:
                input_root = Path(workdir) / "input"
                scratch_root = Path(workdir) / "scratch"
                input_root.mkdir()
                scratch_root.mkdir()
                if not self.allow_unsandboxed:
                    provider = self.sandbox_provider
                    verify_filesystem = getattr(provider, "verify_filesystem_isolation", None)
                    if not callable(verify_filesystem) or verify_filesystem(scratch_root) is not True:
                        raise PluginRunError(
                            "filesystem isolation cannot be independently verified",
                            metadata=metadata,
                        )
                environment = {
                    "DOCS_PLUGIN_INPUT_ROOT": str(input_root),
                    "DOCS_PLUGIN_NETWORK": "disabled" if not manifest.network else "enabled-by-sandbox",
                    "DOCS_PLUGIN_SCRATCH_ROOT": str(scratch_root),
                    "PATH": str(Path(sys.executable).parent),
                    "PYTHONIOENCODING": "utf-8",
                }
                command = self._platform_sandbox_command(manifest.entrypoint)
                # An untrusted Windows plugin must be contained by a Job
                # Object from before spawn through cleanup. Trusted
                # unsandboxed execution intentionally keeps its legacy path.
                job = self._create_windows_job()
                process: subprocess.Popen[bytes] | None = None
                writer: threading.Thread | None = None
                readers: list[threading.Thread] = []
                try:
                    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
                    if job is not None:
                        # Popen closes the primary thread handle, so the
                        # resume helper below reopens the suspended thread.
                        creationflags |= getattr(subprocess, "CREATE_SUSPENDED", 0x00000004)
                    process = subprocess.Popen(command, cwd=scratch_root, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment, shell=False, text=False, creationflags=creationflags, start_new_session=os.name != "nt")
                    if job is not None:
                        self._assign_windows_job(job, process)
                        self._resume_windows_process(job.api, process)
                    assert process.stdin is not None and process.stdout is not None and process.stderr is not None
                    stdout = bytearray()
                    stderr = bytearray()
                    output_overflow = threading.Event()
                    readers = [threading.Thread(target=self._read_limited, args=(process.stdout, stdout, output_overflow), daemon=True), threading.Thread(target=self._read_limited, args=(process.stderr, stderr, output_overflow), daemon=True)]
                    for reader in readers:
                        reader.start()
                    writer = threading.Thread(target=self._write_input, args=(process.stdin, encoded.encode("utf-8")), daemon=True)
                    writer.start()
                    self._monitor(process, scratch_root, stdout, stderr, writer, readers, metadata, output_overflow)
                    raw_stdout = bytes(stdout).decode("utf-8")
                    try:
                        output = json.loads(raw_stdout, parse_constant=self._reject_non_finite)
                    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                        raise PluginRunError("plugin stdout must be one finite JSON value", metadata=metadata) from exc
                    return PluginRunResult(output, manifest_hash(output), raw_stdout, metadata, identity, manifest_identity(manifest), dict(manifest.toolchain), generate_sbom(manifest))
                finally:
                    if process is not None:
                        self._cleanup_process(process, writer, readers, metadata, job)
                    elif job is not None:
                        self._close_windows_job(job)
        except PluginRunError:
            raise
        except Exception as exc:
            raise PluginRunError("plugin cleanup failed", metadata=metadata) from exc

    def _monitor(self, process: subprocess.Popen[bytes], scratch_root: Path, stdout: bytearray, stderr: bytearray, writer: threading.Thread, readers: list[threading.Thread], metadata: dict[str, object], output_overflow: threading.Event) -> None:
        deadline = time.monotonic() + self.timeout_seconds
        while process.poll() is None and time.monotonic() < deadline and not output_overflow.is_set():
            usage = self._scratch_usage(scratch_root)
            metadata["scratch"] = self._scratch_metadata(usage)
            if usage[0] > self.max_scratch_bytes:
                raise PluginRunError("plugin scratch byte limit exceeded", metadata=metadata)
            if usage[1] > self.max_scratch_files:
                raise PluginRunError("plugin scratch file limit exceeded", metadata=metadata)
            time.sleep(0.005)
        if process.poll() is None:
            raise PluginRunError("plugin output limit exceeded" if output_overflow.is_set() else "plugin timed out", metadata=metadata)
        writer.join(timeout=0.1)
        for reader in readers:
            reader.join(timeout=1)
        if output_overflow.is_set() or len(stdout) > self.max_output_bytes or len(stderr) > self.max_output_bytes:
            raise PluginRunError("plugin output limit exceeded", metadata=metadata)
        usage = self._scratch_usage(scratch_root)
        metadata["scratch"] = self._scratch_metadata(usage)
        if usage[0] > self.max_scratch_bytes:
            raise PluginRunError("plugin scratch byte limit exceeded", metadata=metadata)
        if usage[1] > self.max_scratch_files:
            raise PluginRunError("plugin scratch file limit exceeded", metadata=metadata)
        if process.returncode:
            detail = self._safe_stderr(bytes(stderr))
            raise PluginRunError(f"plugin exited with status {process.returncode}: {detail}", metadata=metadata)

    def _create_windows_job(self) -> _WindowsJobObject | None:
        if os.name != "nt" or self.allow_unsandboxed:
            return None
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            create_job = kernel32.CreateJobObjectW
            set_information = kernel32.SetInformationJobObject
            assign_process = kernel32.AssignProcessToJobObject
            terminate_job = kernel32.TerminateJobObject
            close_handle = kernel32.CloseHandle
            is_process_in_job = kernel32.IsProcessInJob
            get_current_process = kernel32.GetCurrentProcess
        except (AttributeError, OSError) as exc:
            raise PluginRunError("Windows Job Objects are unavailable; refusing untrusted plugin execution") from exc

        create_job.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        create_job.restype = ctypes.c_void_p
        set_information.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
        set_information.restype = ctypes.c_int
        assign_process.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        assign_process.restype = ctypes.c_int
        terminate_job.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        terminate_job.restype = ctypes.c_int
        close_handle.argtypes = [ctypes.c_void_p]
        close_handle.restype = ctypes.c_int
        is_process_in_job.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
        is_process_in_job.restype = ctypes.c_int
        get_current_process.argtypes = []
        get_current_process.restype = ctypes.c_void_p

        ctypes.set_last_error(0)
        in_parent_job_value = ctypes.c_int()
        if not is_process_in_job(get_current_process(), None, ctypes.byref(in_parent_job_value)):
            error = ctypes.get_last_error()
            raise PluginRunError(f"IsProcessInJob failed with Win32 error {error}; refusing untrusted plugin execution")
        in_parent_job = bool(in_parent_job_value.value)
        if in_parent_job:
            version = sys.getwindowsversion()
            if (version.major, version.minor) < (6, 2):
                raise PluginRunError("Windows host forbids nested Job Objects; refusing untrusted plugin execution")

        handle = create_job(None, None)
        if not handle:
            error = ctypes.get_last_error()
            raise PluginRunError(f"CreateJobObjectW failed with Win32 error {error}; refusing untrusted plugin execution")
        job = _WindowsJobObject(kernel32, handle)
        limits = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        limits.BasicLimitInformation.LimitFlags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not set_information(job.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):  # JobObjectExtendedLimitInformation
            error = ctypes.get_last_error()
            self._close_windows_job(job)
            raise PluginRunError(f"SetInformationJobObject failed with Win32 error {error}; refusing untrusted plugin execution")
        return job

    def _assign_windows_job(self, job: _WindowsJobObject, process: subprocess.Popen[bytes]) -> None:
        process_handle = getattr(process, "_handle", None)
        if process_handle is None:
            raise PluginRunError("Windows process handle unavailable; refusing untrusted plugin execution")
        with suppress(TypeError, ValueError):
            process_handle = int(process_handle)
        if not job.api.AssignProcessToJobObject(job.handle, process_handle):
            error = ctypes.get_last_error()
            raise PluginRunError(f"AssignProcessToJobObject failed with Win32 error {error}; refusing untrusted plugin execution")
        associated = ctypes.c_int()
        if not job.api.IsProcessInJob(process_handle, job.handle, ctypes.byref(associated)) or not associated.value:
            error = ctypes.get_last_error()
            raise PluginRunError(f"Windows process was not contained by Job Object (Win32 error {error}); refusing untrusted plugin execution")

    def _resume_windows_process(self, api: Any, process: subprocess.Popen[bytes]) -> None:
        create_snapshot = api.CreateToolhelp32Snapshot
        thread_first = api.Thread32First
        thread_next = api.Thread32Next
        open_thread = api.OpenThread
        resume_thread = api.ResumeThread
        close_handle = api.CloseHandle
        create_snapshot.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
        create_snapshot.restype = ctypes.c_void_p
        thread_first.argtypes = [ctypes.c_void_p, ctypes.POINTER(_THREADENTRY32)]
        thread_first.restype = ctypes.c_int
        thread_next.argtypes = [ctypes.c_void_p, ctypes.POINTER(_THREADENTRY32)]
        thread_next.restype = ctypes.c_int
        open_thread.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        open_thread.restype = ctypes.c_void_p
        resume_thread.argtypes = [ctypes.c_void_p]
        resume_thread.restype = ctypes.c_uint32
        close_handle.argtypes = [ctypes.c_void_p]
        close_handle.restype = ctypes.c_int

        snapshot = create_snapshot(0x00000004, 0)  # TH32CS_SNAPTHREAD
        snapshot_value = snapshot.value if isinstance(snapshot, ctypes.c_void_p) else snapshot
        invalid_handle = ctypes.c_void_p(-1).value
        if not snapshot or snapshot_value == invalid_handle:
            error = ctypes.get_last_error()
            raise PluginRunError(f"CreateToolhelp32Snapshot failed with Win32 error {error}; refusing untrusted plugin execution")

        thread_ids: list[int] = []
        entry = _THREADENTRY32()
        entry.dwSize = ctypes.sizeof(entry)
        try:
            has_entry = bool(thread_first(snapshot, ctypes.byref(entry)))
            while has_entry:
                if entry.th32OwnerProcessID == process.pid:
                    thread_ids.append(entry.th32ThreadID)
                has_entry = bool(thread_next(snapshot, ctypes.byref(entry)))
        finally:
            close_handle(snapshot)
        if len(thread_ids) != 1:
            raise PluginRunError("Windows suspended process primary thread unavailable; refusing untrusted plugin execution")

        thread_handle = open_thread(0x0002, 0, thread_ids[0])  # THREAD_SUSPEND_RESUME
        if not thread_handle:
            error = ctypes.get_last_error()
            raise PluginRunError(f"OpenThread failed with Win32 error {error}; refusing untrusted plugin execution")
        try:
            if resume_thread(thread_handle) == 0xFFFFFFFF:
                error = ctypes.get_last_error()
                raise PluginRunError(f"ResumeThread failed with Win32 error {error}; refusing untrusted plugin execution")
        finally:
            close_handle(thread_handle)

    @staticmethod
    def _close_windows_job(job: _WindowsJobObject) -> bool:
        return bool(job.api.CloseHandle(job.handle))

    def _validate_manifest_contract(self, manifest: PluginManifest) -> None:
        limits = manifest.resource_limits
        checks = {
            "timeout_seconds": self.timeout_seconds,
            "output_bytes": self.max_output_bytes,
            "scratch_bytes": self.max_scratch_bytes,
            "scratch_files": self.max_scratch_files,
        }
        for name, runner_limit in checks.items():
            requested = limits.get(name)
            if requested is not None and requested > runner_limit:
                raise PluginRunError(f"manifest resource limit exceeds runner limit: {name}")
        if not manifest.permissions <= frozenset({"read_input", "write_scratch"}):
            raise PluginRunError("plugin requested unsupported permission")

    @staticmethod
    def _reject_non_finite(value: str) -> Any:
        raise ValueError(f"non-finite JSON value: {value}")

    def _sandbox_attestation(self, requested: frozenset[str] | None = None) -> SandboxAttestation | None:
        provider = self.sandbox_provider
        if provider is None:
            return None
        try:
            attestation = provider.attest(self.requested_isolation if requested is None else requested)
        except Exception as exc:
            raise PluginRunError("sandbox provider attestation failed") from exc
        if not isinstance(attestation, SandboxAttestation) or not attestation.provider.strip():
            raise PluginRunError("sandbox provider returned invalid attestation")
        return attestation

    def _platform_sandbox_command(self, entrypoint: tuple[str, ...]) -> tuple[str, ...]:
        if self.allow_unsandboxed:
            return entrypoint
        provider = self.sandbox_provider
        if provider is None:
            raise PluginRunError("untrusted plugin requires an OS-enforced sandbox")
        try:
            command = provider.command(entrypoint)
        except Exception as exc:
            raise PluginRunError("sandbox provider could not create command") from exc
        if not isinstance(command, tuple) or not command or not all(isinstance(part, str) and part for part in command):
            raise PluginRunError("sandbox provider returned invalid command")
        return command

    def _scratch_usage(self, root: Path) -> tuple[int, int]:
        total_bytes = 0
        total_files = 0
        try:
            for path in root.rglob("*"):
                if path.is_file() or path.is_symlink():
                    total_files += 1
                    total_bytes += path.lstat().st_size
        except OSError as exc:
            raise PluginRunError("plugin scratch usage could not be determined") from exc
        return total_bytes, total_files

    def _scratch_metadata(self, usage: tuple[int, int]) -> dict[str, int]:
        return {"byte_limit": self.max_scratch_bytes, "file_limit": self.max_scratch_files, "bytes_used": usage[0], "files_used": usage[1]}

    def _safe_stderr(self, value: bytes) -> str:
        text = value[: self.max_output_bytes].decode("utf-8", errors="replace")
        safe = redact({"stderr": text}).get("stderr", "")
        return str(safe)[: self._MAX_ERROR_TEXT]

    def _cleanup_process(
        self,
        process: subprocess.Popen[bytes],
        writer: threading.Thread | None,
        readers: list[threading.Thread],
        metadata: dict[str, object],
        job: _WindowsJobObject | None = None,
    ) -> None:
        errors: list[str] = []
        job_terminated = False
        if job is not None:
            try:
                job_terminated = bool(job.api.TerminateJobObject(job.handle, 1))
                if not job_terminated:
                    errors.append("windows_job_terminate_failed")
            except Exception:
                errors.append("windows_job_terminate_failed")
        if not job_terminated:
            try:
                # The leader may have exited while descendants still hold pipes.
                self._terminate_process_tree(process)
            except Exception as exc:
                errors.append(type(exc).__name__)
        # Close the parent's handles before joining readers. On Windows,
        # descendants can inherit the pipe handles and keep readers blocked
        # even after the leader has terminated.
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except Exception as exc:
                    errors.append(type(exc).__name__)
        if job is not None:
            try:
                if not self._close_windows_job(job):
                    errors.append("windows_job_close_failed")
            except Exception as exc:
                errors.append(type(exc).__name__)
        if writer is not None:
            writer.join(timeout=0.2)
            if writer.is_alive():
                errors.append("writer_join_timeout")
        readers_deadline = time.monotonic() + 0.5
        for reader in readers:
            remaining = readers_deadline - time.monotonic()
            if remaining > 0:
                reader.join(timeout=remaining)
            if reader.is_alive():
                errors.append("reader_join_timeout")
        try:
            process.wait(timeout=0.2)
        except Exception as exc:
            errors.append(type(exc).__name__)
        if errors:
            # Cleanup diagnostics are bounded and never replace the primary error.
            metadata["cleanup_errors"] = errors[:3]
            if len(errors) > 3:
                metadata["cleanup_errors_truncated"] = True

    def _terminate_process_tree(self, process: subprocess.Popen[bytes]) -> None:
        cleanup_error: Exception | None = None
        if os.name == "nt":
            taskkill: subprocess.Popen[bytes] | None = None
            try:
                taskkill = subprocess.Popen(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                taskkill.wait(timeout=self._CLEANUP_SUBPROCESS_TIMEOUT_SECONDS)
            except Exception as exc:
                cleanup_error = exc
                if taskkill is not None:
                    with suppress(Exception):
                        taskkill.kill()
                    with suppress(Exception):
                        taskkill.wait(timeout=self._CLEANUP_SUBPROCESS_TIMEOUT_SECONDS)
        else:
            killpg = getattr(os, "killpg", None)
            if killpg is not None:
                with suppress(OSError, ProcessLookupError):
                    # start_new_session=True makes the leader PID the stable
                    # process-group ID even after the leader has exited.
                    killpg(process.pid, getattr(signal, "SIGKILL", signal.SIGTERM))
        if process.poll() is None:
            process.kill()
        process.wait(timeout=1)
        if cleanup_error is not None:
            raise cleanup_error

    def _write_input(self, stream: Any, encoded: bytes) -> None:
        try:
            stream.write(encoded)
            stream.flush()
        except (BrokenPipeError, OSError):
            pass
        finally:
            with suppress(OSError):
                stream.close()

    def _read_limited(self, stream: Any, target: bytearray, overflow: threading.Event) -> None:
        while True:
            chunk = stream.read(8192)
            if not chunk:
                return
            remaining = self.max_output_bytes - len(target)
            if remaining <= 0:
                overflow.set()
                return
            target.extend(chunk[:remaining])
            if len(chunk) > remaining:
                overflow.set()
                return
