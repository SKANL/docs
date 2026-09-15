from pathlib import Path

from docs.domain.workspace_config import resolve_workspace_roots

_DEFAULTS = (Path("documents"), Path("templates"))


def test_config_overrides_env_and_default():
    config = {"documents_dir": "cfg-documents", "templates_dir": "cfg-templates"}
    env = {"DOCS_DOCUMENTS_DIR": "env-documents", "DOCS_TEMPLATES_DIR": "env-templates"}
    documents_dir, templates_dir = resolve_workspace_roots(config, env, _DEFAULTS)
    assert documents_dir == Path("cfg-documents")
    assert templates_dir == Path("cfg-templates")


def test_env_overrides_default_when_no_config():
    env = {"DOCS_DOCUMENTS_DIR": "env-documents", "DOCS_TEMPLATES_DIR": "env-templates"}
    documents_dir, templates_dir = resolve_workspace_roots(None, env, _DEFAULTS)
    assert documents_dir == Path("env-documents")
    assert templates_dir == Path("env-templates")


def test_default_used_when_nothing_else_set():
    documents_dir, templates_dir = resolve_workspace_roots(None, {}, _DEFAULTS)
    assert documents_dir == Path("documents")
    assert templates_dir == Path("templates")


def test_config_partial_falls_back_per_field():
    # Only documents_dir set in config; templates_dir should still fall through
    # to env (precedence is per-field, not all-or-nothing).
    config = {"documents_dir": "cfg-documents"}
    env = {"DOCS_TEMPLATES_DIR": "env-templates"}
    documents_dir, templates_dir = resolve_workspace_roots(config, env, _DEFAULTS)
    assert documents_dir == Path("cfg-documents")
    assert templates_dir == Path("env-templates")
