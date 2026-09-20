from datetime import UTC, datetime

import pytest

from docs.api.auth import AuthError, Principal
from docs.api.oidc import (
    BearerTokenValidator,
    JWKSCacheProvider,
    JWKSKeyProvider,
    OIDCValidator,
    ScopePolicy,
    require_policy,
    validate_claims,
)


def _b64(value: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _hs256_token(*, kid="key-1", secret=b"secret", claims=None, algorithm="HS256"):
    import hashlib
    import hmac
    import json

    header = {"alg": algorithm, "kid": kid, "typ": "JWT"}
    payload = claims or {"iss": "issuer", "aud": "docs-api", "sub": "user-1", "exp": 2_000}
    signing_input = f"{_b64(json.dumps(header, separators=(',', ':')).encode())}.{_b64(json.dumps(payload, separators=(',', ':')).encode())}"
    signature = hmac.new(secret, signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64(signature)}"


def test_validate_claims_accepts_issuer_audience_and_expiry_with_skew():
    now = datetime(2026, 1, 1, tzinfo=UTC).timestamp()
    claims = {"iss": "https://issuer.example", "aud": ["docs-api"], "exp": now - 2}

    assert (
        validate_claims(
            claims,
            issuer="https://issuer.example",
            audience="docs-api",
            now=now,
            clock_skew=5,
        )
        == claims
    )


@pytest.mark.parametrize(
    ("claims", "code"),
    [
        ({"iss": "wrong", "aud": "docs-api", "exp": 2_000}, "invalid_issuer"),
        ({"iss": "issuer", "aud": "other", "exp": 2_000}, "invalid_audience"),
        ({"iss": "issuer", "aud": "docs-api", "exp": 900}, "token_expired"),
    ],
)
def test_validate_claims_normalizes_claim_failures(claims, code):
    with pytest.raises(AuthError) as error:
        validate_claims(claims, issuer="issuer", audience="docs-api", now=1_000)

    assert error.value.code == code
    assert error.value.status == 401


def test_validator_uses_injected_jwks_provider_without_networking():
    class Provider:
        def resolve(self, *, key_id, algorithm):
            return {"kid": key_id, "alg": algorithm}

    provider: JWKSKeyProvider = Provider()
    validator = OIDCValidator(issuer="issuer", audience="docs-api", key_provider=provider, now=lambda: 1_000)

    principal = validator.validate(
        {"alg": "RS256", "kid": "key-1"},
        {"iss": "issuer", "aud": "docs-api", "sub": "user-1", "scope": "documents:read", "exp": 1_001},
    )

    assert principal == Principal("user-1", frozenset({"documents:read"}))


def test_validator_maps_tenant_and_organization_claims_to_principal():
    validator = OIDCValidator(
        issuer="issuer",
        audience="docs-api",
        key_provider=lambda **_: {"kid": "key-1"},
        now=lambda: 1_000,
    )

    principal = validator.validate(
        {"alg": "RS256", "kid": "key-1"},
        {
            "iss": "issuer",
            "aud": "docs-api",
            "sub": "user-1",
            "tenant_id": "tenant-a",
            "organization_id": "org-a",
            "exp": 1_001,
        },
    )

    assert principal.tenant_id == "tenant-a"
    assert principal.organization_id == "org-a"


def test_validator_rejects_missing_key_and_scope_policy_is_explicit():
    validator = OIDCValidator(issuer="issuer", audience="docs-api", key_provider=lambda **_: None, now=lambda: 1_000)
    with pytest.raises(AuthError, match="signing key"):
        validator.validate(
            {"alg": "RS256", "kid": "missing"}, {"iss": "issuer", "aud": "docs-api", "sub": "u", "exp": 2_000}
        )

    principal = Principal("u", frozenset({"documents:read"}))
    policy = ScopePolicy(any_of=frozenset({"documents:read", "admin"}))
    assert require_policy(principal, policy) is principal
    with pytest.raises(AuthError) as error:
        require_policy(Principal("u", frozenset()), policy)
    assert error.value.code == "insufficient_scope"


def test_signed_bearer_validator_accepts_valid_hs256_token():
    provider = JWKSCacheProvider(
        fetcher=lambda: {"keys": [{"kty": "oct", "kid": "key-1", "alg": "HS256", "k": _b64(b"secret")}]},
        allowed_algorithms=("HS256",),
        now=lambda: 1_000,
    )
    validator = BearerTokenValidator(issuer="issuer", audience="docs-api", key_provider=provider, now=lambda: 1_000)

    assert validator(_hs256_token()) == Principal("user-1", frozenset())


def test_signed_bearer_validator_rejects_bad_signature_and_none_algorithm():
    provider = JWKSCacheProvider(
        fetcher=lambda: {"keys": [{"kty": "oct", "kid": "key-1", "alg": "HS256", "k": _b64(b"secret")}]},
        allowed_algorithms=("HS256",),
    )
    validator = BearerTokenValidator(issuer="issuer", audience="docs-api", key_provider=provider)

    with pytest.raises(AuthError) as bad:
        validator(_hs256_token(secret=b"wrong"))
    assert bad.value.code == "invalid_token"
    with pytest.raises(AuthError) as none:
        validator(_hs256_token(algorithm="none"))
    assert none.value.code == "invalid_token"


def test_signed_bearer_validator_rejects_missing_kid_unsupported_algorithm_and_confusion():
    provider = JWKSCacheProvider(
        fetcher=lambda: {
            "keys": [{"kty": "RSA", "kid": "key-1", "alg": "HS256", "n": "not-a-secret", "e": "AQAB"}]
        },
        allowed_algorithms=("HS256",),
    )
    validator = BearerTokenValidator(issuer="issuer", audience="docs-api", key_provider=provider)

    with pytest.raises(AuthError):
        validator(_hs256_token(kid=""))
    with pytest.raises(AuthError):
        validator(_hs256_token(algorithm="PS256"))
    with pytest.raises(AuthError):
        validator(_hs256_token())


@pytest.mark.parametrize(
    "claim",
    [
        {"iss": "wrong", "aud": "docs-api", "sub": "u", "exp": 2_000},
        {"iss": "issuer", "aud": "wrong", "sub": "u", "exp": 2_000},
        {"iss": "issuer", "aud": "docs-api", "sub": "u", "exp": 999},
        {"iss": "issuer", "aud": "docs-api", "sub": "u", "exp": "soon"},
    ],
)
def test_signed_bearer_validator_applies_claim_validation(claim):
    provider = JWKSCacheProvider(
        fetcher=lambda: {"keys": [{"kty": "oct", "kid": "key-1", "alg": "HS256", "k": _b64(b"secret")}]},
        allowed_algorithms=("HS256",),
    )
    validator = BearerTokenValidator(issuer="issuer", audience="docs-api", key_provider=provider, now=lambda: 1_000)
    with pytest.raises(AuthError):
        validator(_hs256_token(claims=claim))


def test_jwks_provider_refreshes_once_for_unknown_kid_and_honors_ttl():
    clock = [100.0]
    calls = []

    def fetch():
        calls.append(clock[0])
        kid = "key-2" if len(calls) > 1 else "key-1"
        return {"keys": [{"kty": "oct", "kid": kid, "alg": "HS256", "k": _b64(b"secret")}]}

    provider = JWKSCacheProvider(fetcher=fetch, allowed_algorithms=("HS256",), ttl=10, now=lambda: clock[0])
    assert provider.resolve(key_id="key-1", algorithm="HS256") == b"secret"
    assert provider.resolve(key_id="key-2", algorithm="HS256") == b"secret"
    assert len(calls) == 2
    clock[0] = 105
    assert provider.resolve(key_id="key-2", algorithm="HS256") == b"secret"
    assert len(calls) == 2
    clock[0] = 111
    assert provider.resolve(key_id="key-2", algorithm="HS256") == b"secret"
    assert len(calls) == 3


def test_jwks_provider_does_not_refresh_repeated_unknown_kids_within_generation():
    calls = []
    provider = JWKSCacheProvider(
        fetcher=lambda: calls.append(True) or {
            "keys": [{"kty": "oct", "kid": "known", "alg": "HS256", "k": _b64(b"secret")}]
        },
        allowed_algorithms=("HS256",),
        now=lambda: 100.0,
    )

    assert provider.resolve(key_id="missing", algorithm="HS256") is None
    assert provider.resolve(key_id="missing", algorithm="HS256") is None
    assert len(calls) == 2


def test_jwks_provider_exposes_unavailable_state_and_rejects_malformed_document():
    provider = JWKSCacheProvider(fetcher=lambda: {"keys": [{"kid": "missing-kty"}]}, allowed_algorithms=("HS256",))
    assert provider.resolve(key_id="key-1", algorithm="HS256") is None
    assert provider.status.available is False
    assert provider.status.error == "invalid_jwks"


def test_signed_bearer_validator_fails_closed_when_crypto_backend_unavailable(monkeypatch):
    provider = JWKSCacheProvider(
        fetcher=lambda: {"keys": [{"kty": "oct", "kid": "key-1", "alg": "HS256", "k": _b64(b"secret")}]},
        allowed_algorithms=("RS256",),
    )
    validator = BearerTokenValidator(issuer="issuer", audience="docs-api", key_provider=provider)
    monkeypatch.setattr(validator, "crypto_available", False)
    with pytest.raises(AuthError) as error:
        validator(_hs256_token())
    assert error.value.code == "crypto_unavailable"
