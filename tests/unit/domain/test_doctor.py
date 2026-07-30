from __future__ import annotations

from docs.domain.doctor import Check, DoctorResult, find_manual_like


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


def test_find_manual_like_matches_normative_keyword_with_document_extension():
    candidates = [
        ("random/deep/normativa-institucional.pdf", "pdf"),
        ("random/deep/photo.png", "png"),
    ]
    assert find_manual_like(candidates) == "random/deep/normativa-institucional.pdf"


def test_find_manual_like_ignores_keyword_match_on_a_non_document_extension():
    candidates = [("random/manual.png", "png")]
    assert find_manual_like(candidates) is None


def test_find_manual_like_ignores_document_with_no_keyword_match():
    candidates = [("random/deep/report.pdf", "pdf")]
    assert find_manual_like(candidates) is None


def test_find_manual_like_returns_none_for_no_candidates():
    assert find_manual_like([]) is None


def test_find_manual_like_is_deterministic_and_picks_lowest_sorted_path():
    candidates = [
        ("z/reglas.md", "md"),
        ("a/normativa.pdf", "pdf"),
    ]
    assert find_manual_like(candidates) == "a/normativa.pdf"
