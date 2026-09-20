"""Dependency-free OIDC claim validation and RBAC policy interfaces."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .auth import AuthError, Principal

_MAX_JWKS_TTL = 86_400.0
_ASYMMETRIC_ALGORITHMS = frozenset({"RS256", "RS384", "RS512", "ES256", "ES384", "ES512"})


@runtime_checkable
class JWKSKeyProvider(Protocol):
    """Resolve a signing key from an already-injected JWKS cache or adapter."""

    def resolve(self, *, key_id: str, algorithm: str) -> object | None: ...


def _now_seconds(value: float | int | datetime | None) -> float:
    if value is None:
        return datetime.now(UTC).timestamp()
    if isinstance(value, datetime):
        return value.timestamp()
    return float(value)


def _audiences(value: object) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return {item for item in value if isinstance(item, str)}
    return set()


def validate_claims(
    claims: Mapping[str, Any],
    *,
    issuer: str,
    audience: str | Sequence[str],
    now: float | int | datetime | None = None,
    clock_skew: float = 0,
) -> Mapping[str, Any]:
    """Validate the OIDC claims required by the API boundary."""
    current = _now_seconds(now)
    if clock_skew < 0:
        raise ValueError("clock_skew must be non-negative")
    if claims.get("iss") != issuer:
        raise AuthError("invalid_issuer", "OIDC issuer is invalid")
    expected_audiences = (
        {audience}
        if isinstance(audience, str)
        else {item for item in audience if isinstance(item, str)}
        if isinstance(audience, Sequence)
        else set()
    )
    if not expected_audiences or not (_audiences(claims.get("aud")) & expected_audiences):
        raise AuthError("invalid_audience", "OIDC audience is invalid")
    expiry = claims.get("exp")
    if not isinstance(expiry, (int, float)) or isinstance(expiry, bool):
        raise AuthError("invalid_expiry", "OIDC expiry is invalid")
    if current >= float(expiry) + clock_skew:
        raise AuthError("token_expired", "OIDC token has expired")
    return claims


def _resolve_key(
    provider: JWKSKeyProvider | Callable[..., object | None], *, key_id: str, algorithm: str
) -> object | None:
    resolver = getattr(provider, "resolve", None)
    if callable(resolver):
        return resolver(key_id=key_id, algorithm=algorithm)
    if not callable(provider):
        return None
    return provider(key_id=key_id, algorithm=algorithm)


@dataclass(frozen=True, slots=True)
class JWKSStatus:
    """Safe, non-sensitive provider state suitable for health endpoints."""

    available: bool
    error: str | None = None
    expires_at: float | None = None


class JWKSCacheProvider:
    """Bounded, fail-closed JWKS provider with injected or HTTPS loading."""

    def __init__(
        self,
        *,
        fetcher: Callable[[], object] | None = None,
        url: str | None = None,
        ttl: float = 300,
        timeout: float = 5,
        allowed_algorithms: Sequence[str] = (
            "RS256",
            "RS384",
            "RS512",
            "ES256",
            "ES384",
            "ES512",
            "HS256",
            "HS384",
            "HS512",
        ),
        now: Callable[[], float] | None = None,
    ) -> None:
        if (fetcher is None) == (url is None):
            raise ValueError("provide exactly one JWKS fetcher or HTTPS URL")
        if url is not None and urlparse(url).scheme != "https":
            raise ValueError("JWKS URL must use HTTPS")
        if ttl < 0 or ttl > _MAX_JWKS_TTL or timeout <= 0:
            raise ValueError("ttl must be between 0 and 86400 seconds and timeout must be positive")
        self.fetcher = fetcher or (lambda: self._fetch_url(url or "", timeout))
        self.ttl = float(ttl)
        self.allowed_algorithms = frozenset(allowed_algorithms)
        self.now = now or time.time
        self._keys: dict[tuple[str, str], object] | None = None
        self._expires_at: float | None = None
        self._refresh_attempted: set[str] = set()
        self._status = JWKSStatus(False, "not_loaded")

    @staticmethod
    def _fetch_url(url: str, timeout: float) -> object:
        request = Request(url, headers={"Accept": "application/json"})
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())

    @property
    def status(self) -> JWKSStatus:
        return self._status

    def _load(self, *, reset_refresh_attempts: bool = True) -> bool:
        try:
            document = self.fetcher()
            if isinstance(document, (str, bytes, bytearray)):
                document = json.loads(document)
            if not isinstance(document, Mapping) or not isinstance(document.get("keys"), list):
                raise ValueError("keys must be a list")
            keys: dict[tuple[str, str], object] = {}
            for jwk in document["keys"]:
                if not isinstance(jwk, Mapping):
                    raise ValueError("key must be an object")
                kid, algorithm, kty = jwk.get("kid"), jwk.get("alg"), jwk.get("kty")
                if not isinstance(kid, str) or not kid:
                    raise ValueError("key metadata is invalid")
                if not isinstance(algorithm, str) or not algorithm:
                    raise ValueError("key metadata is invalid")
                if not isinstance(kty, str) or not kty:
                    raise ValueError("key metadata is invalid")
                if algorithm not in self.allowed_algorithms:
                    continue
                if kty == "oct":
                    encoded = jwk.get("k")
                    if not isinstance(encoded, str) or not encoded:
                        raise ValueError("oct key material is invalid")
                    key: object = _b64decode(encoded)
                elif kty in {"RSA", "EC"}:
                    key = dict(jwk)
                else:
                    raise ValueError("unsupported key type")
                keys[(kid, algorithm)] = key
            if not keys:
                raise ValueError("JWKS contains no supported keys")
        except Exception:
            self._keys = None
            self._expires_at = None
            self._status = JWKSStatus(False, "invalid_jwks")
            if reset_refresh_attempts:
                self._refresh_attempted.clear()
            return False
        self._keys = keys
        self._expires_at = self.now() + self.ttl
        if reset_refresh_attempts:
            self._refresh_attempted.clear()
        self._status = JWKSStatus(True, None, self._expires_at)
        return True

    def resolve(self, *, key_id: str, algorithm: str) -> object | None:
        if (
            not isinstance(algorithm, str)
            or algorithm not in self.allowed_algorithms
            or not isinstance(key_id, str)
            or not key_id
        ):
            self._status = JWKSStatus(False, "unsupported_algorithm")
            return None
        current = self.now()
        if (self._keys is None or self._expires_at is None or current >= self._expires_at) and not self._load():
            return None
        key = self._keys.get((key_id, algorithm)) if self._keys else None
        if key is None and key_id not in self._refresh_attempted:
            self._refresh_attempted.add(key_id)
            self._load(reset_refresh_attempts=False)
            key = self._keys.get((key_id, algorithm)) if self._keys else None
        return key


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _json_segment(value: str) -> Mapping[str, Any]:
    try:
        parsed = json.loads(_b64decode(value))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error):
        raise AuthError("invalid_token", "Bearer token is malformed") from None
    if not isinstance(parsed, Mapping):
        raise AuthError("invalid_token", "Bearer token claims are malformed")
    return parsed


class BearerTokenValidator:
    """Verify a compact signed JWT, then reuse the dependency-free claim validator."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str | Sequence[str],
        key_provider: JWKSKeyProvider | Callable[..., object | None],
        clock_skew: float = 0,
        now: Callable[[], float | int | datetime] | None = None,
        allowed_algorithms: Sequence[str] = (
            "RS256",
            "RS384",
            "RS512",
            "ES256",
            "ES384",
            "ES512",
            "HS256",
            "HS384",
            "HS512",
        ),
    ) -> None:
        if clock_skew < 0 or clock_skew > 300:
            raise ValueError("clock_skew must be between 0 and 300 seconds")
        self.issuer, self.audience, self.key_provider = issuer, audience, key_provider
        self.clock_skew = clock_skew
        self.now = now or (lambda: datetime.now(UTC).timestamp())
        self.allowed_algorithms = frozenset(allowed_algorithms)
        self.crypto_available = True

    def __call__(self, token: str) -> Principal:
        return self.validate(token)

    def validate(self, token: str) -> Principal:
        if not isinstance(token, str):
            raise AuthError("invalid_token", "Bearer token is malformed")
        parts = token.split(".")
        if len(parts) != 3 or any(not part for part in parts):
            raise AuthError("invalid_token", "Bearer token is malformed")
        header = _json_segment(parts[0])
        claims = _json_segment(parts[1])
        algorithm, key_id = header.get("alg"), header.get("kid")
        if (
            not isinstance(algorithm, str)
            or algorithm == "none"
            or algorithm not in self.allowed_algorithms
            or not isinstance(key_id, str)
            or not key_id
        ):
            raise AuthError("invalid_token", "OIDC signing metadata is invalid")
        if not self.crypto_available or (
            algorithm in _ASYMMETRIC_ALGORITHMS and not _jwt_available()
        ):
            raise AuthError("crypto_unavailable", "OIDC crypto backend is unavailable")
        key = _resolve_key(self.key_provider, key_id=key_id, algorithm=algorithm)
        if key is None:
            raise AuthError("invalid_token", "OIDC signing key is unavailable")
        if not _verify_signature(parts[0] + "." + parts[1], parts[2], algorithm, key):
            raise AuthError("invalid_token", "OIDC token signature is invalid")
        validate_claims(claims, issuer=self.issuer, audience=self.audience, now=self.now(), clock_skew=self.clock_skew)
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise AuthError("invalid_subject", "OIDC subject is invalid")
        raw_scopes = claims.get("scope", claims.get("scp", ""))
        if isinstance(raw_scopes, str):
            scopes = frozenset(raw_scopes.split())
        elif isinstance(raw_scopes, Sequence) and not isinstance(raw_scopes, (bytes, bytearray)):
            scopes = frozenset(item for item in raw_scopes if isinstance(item, str))
        else:
            raise AuthError("invalid_scope", "OIDC scope claim is invalid")
        return _principal(subject, scopes, claims)


def _verify_signature(signing_input: str, encoded_signature: str, algorithm: str, key: object) -> bool:
    if algorithm.startswith("HS"):
        if not isinstance(key, bytes):
            return False
        digest = getattr(hashlib, "sha" + algorithm[2:], None)
        if digest is None:
            return False
        expected = hmac.new(key, signing_input.encode(), digest).digest()
        try:
            return hmac.compare_digest(expected, _b64decode(encoded_signature))
        except (ValueError, binascii.Error):
            return False
    try:
        import jwt  # type: ignore[import-not-found]

        if isinstance(key, Mapping):
            key = jwt.PyJWK.from_dict(dict(key)).key
        jwt.decode(
            signing_input + "." + encoded_signature,
            key=key,
            algorithms=[algorithm],
            options={
                "verify_aud": False,
                "verify_exp": False,
                "verify_iat": False,
                "verify_nbf": False,
            },
        )
        return True
    except Exception:
        return False


def _jwt_available() -> bool:
    try:
        import jwt  # type: ignore[import-not-found]  # noqa: F401
    except ImportError:
        return False
    return True


SignedBearerTokenValidator = BearerTokenValidator


class OIDCValidator:
    """Validate claims and resolve a signing key without performing I/O."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str | Sequence[str],
        key_provider: JWKSKeyProvider | Callable[..., object | None],
        clock_skew: float = 0,
        now: Callable[[], float | int | datetime] | None = None,
    ) -> None:
        self.issuer = issuer
        self.audience = audience
        self.key_provider = key_provider
        self.clock_skew = clock_skew
        self.now = now or (lambda: datetime.now(UTC).timestamp())

    def validate(self, header: Mapping[str, Any], claims: Mapping[str, Any]) -> Principal:
        algorithm = header.get("alg")
        key_id = header.get("kid")
        if not isinstance(algorithm, str) or not algorithm or not isinstance(key_id, str) or not key_id:
            raise AuthError("invalid_token", "OIDC signing metadata is invalid")
        if _resolve_key(self.key_provider, key_id=key_id, algorithm=algorithm) is None:
            raise AuthError("invalid_token", "OIDC signing key is unavailable")
        validate_claims(
            claims,
            issuer=self.issuer,
            audience=self.audience,
            now=self.now(),
            clock_skew=self.clock_skew,
        )
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise AuthError("invalid_subject", "OIDC subject is invalid")
        raw_scopes = claims.get("scope", claims.get("scp", ""))
        if isinstance(raw_scopes, str):
            scopes = frozenset(raw_scopes.split())
        elif isinstance(raw_scopes, Sequence) and not isinstance(raw_scopes, (bytes, bytearray)):
            scopes = frozenset(item for item in raw_scopes if isinstance(item, str))
        else:
            scopes = frozenset()
        return _principal(subject, scopes, claims)


def _principal(subject: str, scopes: frozenset[str], claims: Mapping[str, Any]) -> Principal:
    tenant_id = claims.get("tenant_id")
    organization_id = claims.get("organization_id")
    return Principal(
        subject,
        scopes,
        tenant_id=tenant_id if isinstance(tenant_id, str) and tenant_id else None,
        organization_id=(
            organization_id if isinstance(organization_id, str) and organization_id else None
        ),
    )


@dataclass(frozen=True, slots=True)
class ScopePolicy:
    """An RBAC policy requiring every ``all_of`` or one ``any_of`` scope."""

    all_of: frozenset[str] = frozenset()
    any_of: frozenset[str] = frozenset()


def require_policy(principal: Principal, policy: ScopePolicy) -> Principal:
    if not policy.all_of.issubset(principal.scopes) or (
        policy.any_of and not policy.any_of.intersection(principal.scopes)
    ):
        raise AuthError("insufficient_scope", "Required scope is missing", 403)
    return principal


def scope_policy(*, all_of: Sequence[str] = (), any_of: Sequence[str] = ()) -> ScopePolicy:
    """Build a normalized immutable RBAC scope policy."""
    return ScopePolicy(frozenset(all_of), frozenset(any_of))
