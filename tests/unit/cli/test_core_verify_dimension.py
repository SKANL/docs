from docs.cli.commands.core_app import _filter_review_dimensions
from docs.domain.review import Issue, ReviewDimension, ReviewResult


def test_filter_review_dimensions_keeps_only_requested_findings():
    result = ReviewResult(
        [
            Issue("warning", "copy", dimension=ReviewDimension.EDITORIAL),
            Issue("error", "layout", dimension=ReviewDimension.VISUAL),
        ]
    )

    filtered = _filter_review_dimensions(result, [ReviewDimension.VISUAL])

    assert filtered.issues == [result.issues[1]]
    assert filtered.passed is False
