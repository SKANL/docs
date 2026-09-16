from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, ClassVar

from docs.domain.contracts import Passport

EVIDENCE_PASSPORT_SCHEMA = "docs.evidence-passport/v1"
REDACTED = "[REDACTED]"


@dataclass(frozen=True)
class RedactionPolicy:
    sensitive_key_fragments: tuple[str, ...] = (
        "password",
        "secret",
        "token",
        "credential",
        "api_key",
        "authorization",
        "cookie",
        "private_key",
    )
    sensitive_path_components: tuple[str, ...] = (
        ".aws",
        ".azure",
        ".gnupg",
        ".ssh",
        "credentials",
        "id_ed25519",
        "id_rsa",
        "secrets",
    )
    replacement: str = REDACTED


DEFAULT_REDACTION_POLICY = RedactionPolicy()
_SENSITIVE_CONTENT = re.compile(
    r"(?:authorization\s*:|bearer\s+|api\s*[_-]?\s*key\s*[:=]|password\s*[:=]|secret\s*[:=]|token\s*[:=]|-----BEGIN [^-]+PRIVATE KEY-----)",
    re.IGNORECASE,
)


def canonical_json(value: Any) -> bytes:
    """Encode supported JSON values as deterministic compact UTF-8 JSON."""
    return json.dumps(
        _json_value(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def redact(value: Any, policy: RedactionPolicy = DEFAULT_REDACTION_POLICY) -> Any:
    """Return a JSON-shaped copy with likely secrets and sensitive paths removed."""
    if type(value) is str and (_SENSITIVE_CONTENT.search(value) or _is_sensitive_path(value, policy)):
        return policy.replacement
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError("JSON object keys must be strings")
            lowered = key.lower()
            if (
                _is_sensitive_key(lowered, policy)
                or _is_sensitive_path(item, policy)
                or ("content" in lowered and type(item) is str and _SENSITIVE_CONTENT.search(item))
            ):
                result[key] = policy.replacement
            else:
                result[key] = redact(item, policy)
        return result
    if isinstance(value, (list, tuple)):
        return [redact(item, policy) for item in value]
    return value


@dataclass(frozen=True)
class EvidencePassport:
    passport: Passport
    digest: str

    schema: ClassVar[str] = EVIDENCE_PASSPORT_SCHEMA

    def __post_init__(self) -> None:
        if not isinstance(self.passport, Passport):
            raise TypeError("passport must be a Passport")
        if not re.fullmatch(r"[0-9a-f]{64}", self.digest):
            raise ValueError("digest must be a SHA-256 hex digest")
        if self.digest != _digest(self.passport):
            raise ValueError("digest does not match passport")

    @classmethod
    def from_passport_payload(
        cls,
        run_id: str,
        entries: tuple[Mapping[str, Any], ...],
        policy: RedactionPolicy = DEFAULT_REDACTION_POLICY,
    ) -> EvidencePassport:
        redacted_entries = redact(entries, policy)
        passport = Passport(run_id=run_id, entries=tuple(redacted_entries))
        return cls(passport=passport, digest=_digest(passport))

    def to_dict(self) -> dict[str, Any]:
        return {"schema": self.schema, "digest": self.digest, "passport": self.passport.to_dict()}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> EvidencePassport:
        if payload.get("schema") != cls.schema:
            raise ValueError("unsupported EvidencePassport schema")
        passport_payload = payload.get("passport")
        if not isinstance(passport_payload, Mapping):
            raise TypeError("passport must be an object")
        digest = payload.get("digest")
        if type(digest) is not str:
            raise TypeError("digest must be a string")
        return cls(passport=Passport.from_dict(dict(passport_payload)), digest=digest)


def _digest(passport: Passport) -> str:
    payload = {"schema": EVIDENCE_PASSPORT_SCHEMA, "passport": passport.to_dict()}
    return sha256(canonical_json(payload)).hexdigest()


def _json_value(value: Any) -> Any:
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise TypeError("only supported JSON values can be canonicalized")
        return value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError("JSON object keys must be strings")
            result[key] = _json_value(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    raise TypeError("only supported JSON values can be canonicalized")


def _is_sensitive_key(key: str, policy: RedactionPolicy) -> bool:
    normalized_key = re.sub(r"[\s_-]+", "", key).casefold()
    return any(
        re.sub(r"[\s_-]+", "", fragment).casefold() in normalized_key
        for fragment in policy.sensitive_key_fragments
    )


def _is_sensitive_path(value: Any, policy: RedactionPolicy) -> bool:
    if type(value) is not str:
        return False
    components = [component.lower() for component in re.split(r"[\\\\/]", value)]
    return any(component in policy.sensitive_path_components for component in components)

