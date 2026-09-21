from pathlib import Path

import pytest

from docs.api.production import build_application
from docs.api.server import TransportConfig


def test_self_hosted_factory_requires_workspace() -> None:
    with pytest.raises(ValueError, match="workspace is required"):
        build_application(TransportConfig(mode="offline"))


def test_self_hosted_factory_composes_real_authenticated_application(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DOCS_API_TOKENS", "secret=integration-user")
    application = build_application(TransportConfig(workspace=tmp_path, mode="offline"))
    assert application.auth is not None
    principal = application.auth("secret")
    assert principal.tenant_id == "default"
    assert principal.organization_id == "default"
    assert (tmp_path / ".docs" / "workspaces.json").is_file()


def test_self_hosted_factory_rejects_partial_oidc_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DOCS_OIDC_ISSUER", "https://issuer.example")
    monkeypatch.setenv("DOCS_OIDC_AUDIENCE", "docs-api")
    monkeypatch.delenv("DOCS_OIDC_JWKS_URL", raising=False)
    with pytest.raises(ValueError, match="must be configured together"):
        build_application(TransportConfig(workspace=tmp_path, mode="offline"))
