"""Native, lazy implementation of the tool-capability detector port."""

from __future__ import annotations

import importlib.util
import shutil
from collections.abc import Callable
from importlib import metadata

from docs.domain.tool_capability import CapabilityDetection, ToolCapability


class NativeToolCapabilityDetector:
    """Probe PATH and Python metadata only when a registry asks for it."""

    def __init__(self, executable_version: Callable[[str], str | None] | None = None) -> None:
        self._executable_version = executable_version

    def detect(self, capability: ToolCapability) -> CapabilityDetection:
        if capability.module:
            return self._detect_module(capability.module)
        return self._detect_executable(capability.executable)

    @staticmethod
    def _detect_module(module: str) -> CapabilityDetection:
        try:
            found = importlib.util.find_spec(module)
        except ModuleNotFoundError:
            found = None
        if found is None:
            return CapabilityDetection.unavailable(f"Python module not found: {module}")
        return CapabilityDetection.available_at(f"python:{module}", version=_module_version(module))

    def _detect_executable(self, executable: str) -> CapabilityDetection:
        path = shutil.which(executable)
        if path is None:
            return CapabilityDetection.unavailable(f"Executable not found: {executable}")
        version = self._executable_version(path) if self._executable_version else None
        return CapabilityDetection.available_at(path, version=version)


def _module_version(module: str) -> str | None:
    try:
        distributions = metadata.packages_distributions().get(module, ())
        return metadata.version(distributions[0]) if distributions else None
    except metadata.PackageNotFoundError:
        return None
