from __future__ import annotations

from docs.domain.doctor import Check, DoctorResult


def test_check_to_dict_includes_all_fields():
    check = Check("pandoc", True, "/usr/bin/pandoc", required=False)
    assert check.to_dict() == {"name": "pandoc", "ok": True, "required": False, "detail": "/usr/bin/pandoc"}


def test_doctor_result_passed_ignores_non_required_failures():
    result = DoctorResult([Check("optional", False, "missing", required=False)])
    assert result.passed is True


def test_doctor_result_passed_is_false_when_a_required_check_fails():
    result = DoctorResult([Check("required_thing", False, "missing", required=True)])
    assert result.passed is False


def test_doctor_result_to_markdown_uses_ok_fail_warn_markers():
    result = DoctorResult(
        [
            Check("a", True, "fine", required=True),
            Check("b", False, "broken", required=True),
            Check("c", False, "missing but optional", required=False),
        ]
    )
    markdown = result.to_markdown()
    assert "- OK `a`: fine" in markdown
    assert "- FAIL `b`: broken" in markdown
    assert "- WARN `c`: missing but optional" in markdown


def test_doctor_result_to_dict_matches_passed_and_check_dicts():
    check = Check("x", True, "ok")
    result = DoctorResult([check])
    assert result.to_dict() == {"passed": True, "checks": [check.to_dict()]}
