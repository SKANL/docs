"""Dependency-free bearer authentication and scope authorization helpers."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Principal:
    subject: str
    scopes: frozenset[str]


class AuthError(Exception):
    def __init__(self, code: str, message: str, status: int = 401, *, headers: Mapping[str, str] | None = None) -> None:
        super().__init__(message)
        self.code, self.message, self.status, self.headers = code, message, status, headers or {}


TokenValidator = Callable[[str], Principal | None]


def bearer_auth(headers: Mapping[str, str], validator: TokenValidator) -> Principal:
    value = next((v for k, v in headers.items() if k.lower() == "authorization"), "")
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthError("missing_token", "Bearer authentication is required")
    principal = validator(token.strip())
    if principal is None:
        raise AuthError("invalid_token", "Bearer token is invalid")
    return principal


def require_scopes(principal: Principal, *required: str) -> Principal:
    if set(required) - principal.scopes:
        raise AuthError("insufficient_scope", "Required scope is missing", 403)
    return principal
