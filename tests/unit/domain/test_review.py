import inspect

from docs.domain import review as review_module
from docs.domain.review import Issue, ReviewDimension, ReviewResult


def test_module_source_has_no_tesina_literal():
    assert "tesina" not in inspect.getsource(review_module).lower()


def test_review_dimension_exposes_the_supported_categories():
    assert [dimension.value for dimension in ReviewDimension] == [
        "editorial",
        "evidence",
        "consistency",
        "structural",
        "accessibility",
        "visual",
        "reproducibility",
    ]


def test_issue_default_code_is_empty_string():
    issue = Issue(severity="error", message="Algo falló.")
    assert issue.code == ""
    assert issue.dimension is ReviewDimension.EDITORIAL


def test_issue_legacy_positional_call_and_json_use_editorial_dimension():
    issue = Issue("warning", "Cuidado.", "some.code")

    assert issue.to_dict() == {
        "severity": "warning",
        "message": "Cuidado.",
        "code": "some.code",
        "dimension": "editorial",
    }


def test_issue_to_dict():
    issue = Issue(severity="warning", message="Cuidado.", code="some.code")
    assert issue.to_dict() == {
        "severity": "warning",
        "message": "Cuidado.",
        "code": "some.code",
        "dimension": "editorial",
    }


def test_issue_serializes_optional_review_contract_metadata_when_provided():
    issue = Issue(
        severity="error",
        message="Build output changed.",
        dimension=ReviewDimension.REPRODUCIBILITY,
        evidence="SHA-256 mismatch between equivalent builds.",
        resolution_condition="Rebuild produces matching bytes.",
        section="methodology",
        file="output/draft/report.docx",
        page=4,
        stage_originator="reproducibility-check",
    )

    assert issue.to_dict() == {
        "severity": "error",
        "message": "Build output changed.",
        "code": "",
        "dimension": "reproducibility",
        "evidence": "SHA-256 mismatch between equivalent builds.",
        "resolution_condition": "Rebuild produces matching bytes.",
        "section": "methodology",
        "file": "output/draft/report.docx",
        "page": 4,
        "stage_originator": "reproducibility-check",
    }


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
        "issues": [{"severity": "error", "message": "x", "code": "c.code", "dimension": "editorial"}],
    }


def test_filter_dimensions_returns_only_requested_dimensions():
    result = ReviewResult(
        issues=[
            Issue("warning", "Prosa.", dimension=ReviewDimension.EDITORIAL),
            Issue("error", "Estructura.", dimension=ReviewDimension.STRUCTURAL),
        ]
    )

    filtered = result.filter_dimensions({ReviewDimension.STRUCTURAL})

    assert filtered.issues == [Issue("error", "Estructura.", dimension=ReviewDimension.STRUCTURAL)]
    assert filtered.passed is False


def test_filter_dimensions_supports_reproducibility_issues_with_contract_metadata():
    reproducibility_issue = Issue(
        "error",
        "Output changed.",
        dimension=ReviewDimension.REPRODUCIBILITY,
        evidence="SHA-256 mismatch.",
        stage_originator="reproducibility-check",
    )
    result = ReviewResult(
        issues=[
            Issue("warning", "Prosa.", dimension=ReviewDimension.EDITORIAL),
            reproducibility_issue,
        ]
    )

    filtered = result.filter_dimensions({ReviewDimension.REPRODUCIBILITY})

    assert filtered.to_dict() == {
        "passed": False,
        "issues": [
            {
                "severity": "error",
                "message": "Output changed.",
                "code": "",
                "dimension": "reproducibility",
                "evidence": "SHA-256 mismatch.",
                "stage_originator": "reproducibility-check",
            }
        ],
    }
