from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, ClassVar

SCHEMA = "docs.x20/v1"


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_thaw(item) for item in value]
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _mapping(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise TypeError("contract payload must be a dict")
    return dict(payload)


def _text(value: Any, field_name: str, *, non_empty: bool = False) -> str:
    if type(value) is not str or (non_empty and not value):
        message = "a non-empty string" if non_empty else "a string"
        raise TypeError(f"{field_name} must be {message}")
    return value


def _mapping_field(payload: dict[str, Any], field_name: str) -> dict[str, Any]:
    value = payload.get(field_name, {})
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a dict")
    return dict(value)


def _list_field(payload: dict[str, Any], field_name: str) -> list[Any]:
    value = payload.get(field_name, [])
    if type(value) is not list:
        raise TypeError(f"{field_name} must be a list")
    return value


def _non_negative_int(value: Any, field_name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{field_name} must be an int")
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return value


@dataclass(frozen=True)
class _Contract:
    schema: ClassVar[str] = SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {"schema": self.schema, **_thaw(self._payload())}

    @classmethod
    def _check_schema(cls, payload: Any) -> dict[str, Any]:
        payload = _mapping(payload)
        if payload.get("schema") != cls.schema:
            raise ValueError(f"unsupported {cls.__name__} schema")
        return payload

    def _payload(self) -> dict[str, Any]:
        raise NotImplementedError


@dataclass(frozen=True)
class Run(_Contract):
    id: str
    status: str = "queued"
    payload: Mapping[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def __post_init__(self) -> None:
        _text(self.id, "id", non_empty=True)
        _text(self.status, "status")
        _text(self.created_at, "created_at")
        object.__setattr__(self, "payload", _freeze(_mapping(self.payload)))

    def _payload(self) -> dict[str, Any]:
        return {"id": self.id, "status": self.status, "payload": self.payload, "created_at": self.created_at}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Run:
        payload = cls._check_schema(payload)
        return cls(
            _text(payload["id"], "id", non_empty=True),
            _text(payload.get("status", "queued"), "status"),
            _mapping_field(payload, "payload"),
            _text(payload.get("created_at", ""), "created_at"),
        )


@dataclass(frozen=True)
class Passport(_Contract):
    run_id: str
    entries: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        _text(self.run_id, "run_id", non_empty=True)
        if type(self.entries) is not tuple or any(not isinstance(entry, Mapping) for entry in self.entries):
            raise TypeError("entries must contain dicts")
        object.__setattr__(self, "entries", tuple(_freeze(entry) for entry in self.entries))

    def _payload(self) -> dict[str, Any]:
        return {"run_id": self.run_id, "entries": list(self.entries)}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Passport:
        payload = cls._check_schema(payload)
        entries = _list_field(payload, "entries")
        if any(not isinstance(entry, Mapping) for entry in entries):
            raise TypeError("entries must contain dicts")
        return cls(_text(payload["run_id"], "run_id", non_empty=True), tuple(entries))


@dataclass(frozen=True)
class Artifact(_Contract):
    id: str
    run_id: str
    kind: str
    digest: str
    media_type: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _text(self.id, "id", non_empty=True)
        _text(self.run_id, "run_id", non_empty=True)
        _text(self.kind, "kind")
        _text(self.digest, "digest")
        _text(self.media_type, "media_type")
        object.__setattr__(self, "metadata", _freeze(_mapping(self.metadata)))

    def _payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "kind": self.kind,
            "digest": self.digest,
            "media_type": self.media_type,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Artifact:
        payload = cls._check_schema(payload)
        return cls(
            _text(payload["id"], "id", non_empty=True),
            _text(payload["run_id"], "run_id", non_empty=True),
            _text(payload["kind"], "kind"),
            _text(payload["digest"], "digest"),
            _text(payload.get("media_type", ""), "media_type"),
            _mapping_field(payload, "metadata"),
        )


@dataclass(frozen=True)
class Blob(_Contract):
    key: str
    digest: str
    size_bytes: int
    media_type: str = "application/octet-stream"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _text(self.key, "key", non_empty=True)
        _text(self.digest, "digest")
        _non_negative_int(self.size_bytes, "size_bytes")
        _text(self.media_type, "media_type")
        object.__setattr__(self, "metadata", _freeze(_mapping(self.metadata)))

    def _payload(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "digest": self.digest,
            "size_bytes": self.size_bytes,
            "media_type": self.media_type,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Blob:
        payload = cls._check_schema(payload)
        return cls(
            _text(payload["key"], "key", non_empty=True),
            _text(payload["digest"], "digest"),
            _non_negative_int(payload["size_bytes"], "size_bytes"),
            _text(payload.get("media_type", "application/octet-stream"), "media_type"),
            _mapping_field(payload, "metadata"),
        )


@dataclass(frozen=True)
class Graph(_Contract):
    nodes: tuple[str, ...] = ()
    edges: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if type(self.nodes) not in (list, tuple) or any(type(node) is not str or not node for node in self.nodes):
            raise TypeError("nodes must contain non-empty strings")
        if type(self.edges) not in (list, tuple):
            raise TypeError("edges must contain two-item lists of non-empty strings")
        parsed_edges: list[tuple[str, str]] = []
        for edge in self.edges:
            if (
                type(edge) not in (list, tuple)
                or len(edge) != 2
                or any(type(node) is not str or not node for node in edge)
            ):
                raise TypeError("edges must contain two-item lists of non-empty strings")
            parsed_edges.append((edge[0], edge[1]))
        object.__setattr__(self, "nodes", tuple(self.nodes))
        object.__setattr__(self, "edges", tuple(parsed_edges))

    def _payload(self) -> dict[str, Any]:
        return {"nodes": list(self.nodes), "edges": [list(edge) for edge in self.edges]}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Graph:
        payload = cls._check_schema(payload)
        nodes = _list_field(payload, "nodes")
        edges = _list_field(payload, "edges")
        if any(type(node) is not str or not node for node in nodes):
            raise TypeError("nodes must contain non-empty strings")
        parsed_edges: list[tuple[str, str]] = []
        for edge in edges:
            if type(edge) is not list or len(edge) != 2 or any(type(node) is not str or not node for node in edge):
                raise TypeError("edges must contain two-item lists of non-empty strings")
            parsed_edges.append((edge[0], edge[1]))
        return cls(tuple(nodes), tuple(parsed_edges))


@dataclass(frozen=True)
class Job(_Contract):
    id: str
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _text(self.id, "id", non_empty=True)
        object.__setattr__(self, "payload", _freeze(_mapping(self.payload)))

    def _payload(self) -> dict[str, Any]:
        return {"id": self.id, "payload": self.payload}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Job:
        payload = cls._check_schema(payload)
        return cls(_text(payload["id"], "id", non_empty=True), _mapping_field(payload, "payload"))


@dataclass(frozen=True)
class Lease(_Contract):
    resource: str
    owner: str
    ttl_seconds: int

    def __post_init__(self) -> None:
        _text(self.resource, "resource", non_empty=True)
        _text(self.owner, "owner", non_empty=True)
        _non_negative_int(self.ttl_seconds, "ttl_seconds")

    def _payload(self) -> dict[str, Any]:
        return {"resource": self.resource, "owner": self.owner, "ttl_seconds": self.ttl_seconds}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Lease:
        payload = cls._check_schema(payload)
        return cls(
            _text(payload["resource"], "resource", non_empty=True),
            _text(payload["owner"], "owner", non_empty=True),
            _non_negative_int(payload["ttl_seconds"], "ttl_seconds"),
        )
