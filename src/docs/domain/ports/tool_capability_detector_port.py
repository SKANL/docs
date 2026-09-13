"""Port for local external-tool capability detection."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from docs.domain.tool_capability import CapabilityDetection, ToolCapability


class ToolCapabilityDetectorPort(Protocol):
    """Resolve one declared capability without leaking platform I/O inward."""

    def detect(self, capability: ToolCapability) -> CapabilityDetection: ...
