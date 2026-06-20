from docs.domain.models.result import Severity, Issue, ReviewResult


def test_review_passes_when_no_errors():
    result = ReviewResult(issues=[Issue(Severity.WARNING, "soft", code="x")])
    assert result.passed is True


def test_review_fails_on_any_error():
    result = ReviewResult(issues=[Issue(Severity.ERROR, "bad", code="y")])
    assert result.passed is False


def test_issue_to_dict_matches_legacy_shape():
    assert Issue(Severity.ERROR, "m", code="c").to_dict() == {
        "severity": "error", "message": "m", "code": "c",
    }
