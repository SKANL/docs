"""Self-hosted API application factory for ``docs-api`` deployments.

The desktop sidecar remains loopback-only.  This factory is the explicit
remote/self-hosted entry point: it composes the same durable application and
worker runtime, then attaches a small environment-backed bearer-token
validator so ``docs-api`` can be launched without writing a second server.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..domain.workspace_format import validate_workspace_layout, validate_workspace_marker
from ..sidecar import SidecarConfig
from ..sidecar import build_application as build_sidecar_application
from .auth import Principal
from .oidc import BearerTokenValidator, JWKSCacheProvider
from .server import TransportConfig


def build_application(config: TransportConfig):
    """Build the real X20 application used by the remote API entrypoint.

    Configure ``workspace`` in the docs-api JSON and provide
    ``DOCS_API_TOKENS`` as a comma-separated list of ``token`` or
    ``token=subject`` values.  No token means fail closed rather than exposing
    a production deployment anonymously.
    """
    workspace = config.workspace or _workspace_from_environment()
    if workspace is None:
        raise ValueError("workspace is required for the self-hosted API")
    workspace = Path(workspace).expanduser().resolve()
    validate_workspace_layout(workspace, workspace / "documents", workspace / "templates")
    validate_workspace_marker(workspace)
    validator = _token_validator()
    application = build_sidecar_application(
        SidecarConfig(
            host="127.0.0.1",
            port=0,
            workspace=Path(workspace),
            max_body_bytes=config.max_request_body,
            cors_origins=config.cors_origins,
        )
    )
    if application.application is None:
        raise RuntimeError("self-hosted API application failed to initialize")
    application.application.workspace_scoped_auth = True
    application.auth = validator
    return application


def _workspace_from_environment() -> Path | None:
    value = os.environ.get("DOCS_API_WORKSPACE") or os.environ.get("DOCS_SIDECAR_WORKSPACE")
    return Path(value).expanduser() if value else None


def _token_validator():
    oidc_issuer = os.environ.get("DOCS_OIDC_ISSUER", "").strip()
    oidc_audience = os.environ.get("DOCS_OIDC_AUDIENCE", "").strip()
    oidc_jwks_url = os.environ.get("DOCS_OIDC_JWKS_URL", "").strip()
    oidc_values = (oidc_issuer, oidc_audience, oidc_jwks_url)
    if any(oidc_values):
        if not all(oidc_values):
            raise ValueError(
                "DOCS_OIDC_ISSUER, DOCS_OIDC_AUDIENCE, and DOCS_OIDC_JWKS_URL "
                "must be configured together"
            )
        return BearerTokenValidator(
            issuer=oidc_issuer,
            audience=oidc_audience,
            key_provider=JWKSCacheProvider(
                url=oidc_jwks_url,
                ttl=float(os.environ.get("DOCS_OIDC_JWKS_TTL", "300")),
                timeout=float(os.environ.get("DOCS_OIDC_JWKS_TIMEOUT", "5")),
            ),
            clock_skew=float(os.environ.get("DOCS_OIDC_CLOCK_SKEW", "30")),
        )
    raw = os.environ.get("DOCS_API_TOKENS", "")
    entries = {}
    for item in raw.split(","):
        token, _separator, subject = item.strip().partition("=")
        if token:
            entries[token] = subject or "docs-api-user"

    def validate(token: str) -> Principal | None:
        subject = entries.get(token)
        if subject is None:
            return None
        return Principal(
            subject=subject,
            scopes=frozenset({
                "workspaces:read", "workspaces:write", "documents:read", "documents:write",
                "runs:read", "runs:write", "findings:read", "artifacts:read", "passport:read",
                "graph:read", "baselines:read", "baselines:write", "plugins:read",
            }),
            tenant_id=os.environ.get("DOCS_API_TENANT_ID", "default"),
            organization_id=os.environ.get("DOCS_API_ORGANIZATION_ID", "default"),
        )

    return validate


__all__ = ["build_application"]
