import inspect

from docs.domain import review as review_module
from docs.domain.review import Issue, ReviewResult


def test_module_source_has_no_tesina_literal():
    assert "tesina" not in inspect.getsource(review_module).lower()


def test_issue_default_code_is_empty_string():
    issue = Issue(severity="error", message="Algo falló.")
    assert issue.code == ""


def test_issue_to_dict():
    issue = Issue(severity="warning", message="Cuidado.", code="some.code")
    assert issue.to_dict() == {"severity": "warning", "message": "Cuidado.", "code": "some.code"}


def test_review_result_passed_true_when_no_error():
    result = ReviewResult(issues=[Issue(severity="warning", message="x")])
    assert result.passed is True


def test_review_result_passed_false_when_any_error():
    result = ReviewResult(
        issues=[Issue(severity="warning", message="x"), Issue(severity="error", message="y")]
    )
    assert result.passed is False


def test_review_result_passed_true_when_empty():
    result = ReviewResult(issues=[])
    assert result.passed is True


def test_to_markdown_empty_issues():
    result = ReviewResult(issues=[])
    assert result.to_markdown() == "# Revisión\n\nSin hallazgos."


def test_to_markdown_with_issues_uppercases_severity_and_omits_code():
    result = ReviewResult(
        issues=[
            Issue(severity="error", message="Falta título.", code="structure.missing_title"),
            Issue(severity="warning", message="Término subjetivo.", code="voice.subjective_term"),
        ]
    )
    assert result.to_markdown() == (
        "# Revisión\n\n"
        "- ERROR: Falta título.\n"
        "- WARNING: Término subjetivo."
    )


def test_to_dict():
    result = ReviewResult(issues=[Issue(severity="error", message="x", code="c.code")])
    assert result.to_dict() == {
        "passed": False,
        "issues": [{"severity": "error", "message": "x", "code": "c.code"}],
    }
