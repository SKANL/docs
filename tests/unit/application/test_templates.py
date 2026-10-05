"""TemplateService: the one place the CLI and the API write and validate templates."""

import json

import pytest

from docs.application.templates import TemplateError, TemplateService, builtin_names


def test_builtin_names_come_from_package_data():
    assert "documento-generico" in builtin_names()


def test_use_refuses_overwrite_unless_forced(tmp_path):
    service = TemplateService(tmp_path / "templates")
    path = service.use("documento-generico")
    assert path == tmp_path / "templates" / "documento-generico.json"
    with pytest.raises(TemplateError) as exc:
        service.use("documento-generico")
    assert exc.value.code == "template_exists"
    path.write_text("{}", encoding="utf-8")
    service.use("documento-generico", force=True)
    assert json.loads(path.read_text(encoding="utf-8"))["type"]


def test_unknown_builtin_and_unsafe_names_are_refused(tmp_path):
    service = TemplateService(tmp_path)
    with pytest.raises(TemplateError) as exc:
        service.use("nope")
    assert exc.value.code == "builtin_template_not_found"
    for name in ("../x", "a/b", "a\\b", "..", ""):
        with pytest.raises(TemplateError) as unsafe:
            service.create(name)
        assert unsafe.value.code == "invalid_template_name"


def test_create_keeps_the_cli_overwrite_behaviour_behind_a_flag(tmp_path):
    service = TemplateService(tmp_path)
    service.create("x")
    with pytest.raises(TemplateError):
        service.create("x")
    service.create("x", overwrite=True)


def test_validate_turns_unreadable_input_into_issues(tmp_path):
    service = TemplateService(tmp_path)
    (tmp_path / "bad.json").write_text("{", encoding="utf-8")
    assert service.validate("bad").issues[0].code == "template.json.invalid"
    assert service.validate_raw([]).issues[0].code == "template.json.invalid"
    with pytest.raises(TemplateError) as exc:
        service.validate("ghost")
    assert exc.value.code == "template_not_found"
