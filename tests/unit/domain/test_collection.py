# tests/unit/domain/test_collection.py
import pytest

from docs.domain.collection import (
    classify_source,
    dedupe_facts,
    extract_github_repo,
    parse_gh_issues,
)


@pytest.mark.parametrize(
    "source_type,expected",
    [
        ("approved_context", "confirmado"),
        ("institutional_manual", "confirmado"),
        ("mobile_code_or_docs", "confirmado"),
        ("example_reference", "fuera_de_alcance"),
        ("cover_template", "confirmado"),
        ("evidence", "pendiente"),
        ("unknown_type", "pendiente"),
    ],
)
def test_classify_source(source_type, expected):
    assert classify_source(source_type) == expected


def test_parse_gh_issues_empty_string_defaults_to_empty_list():
    assert parse_gh_issues("") == []


def test_parse_gh_issues_invalid_json_raises_value_error_with_spanish_message():
    with pytest.raises(ValueError, match="No se pudo parsear salida JSON de gh"):
        parse_gh_issues("not json")


def test_parse_gh_issues_maps_fields_and_forces_classification():
    raw = (
        '[{"number": 1, "title": "Bug", "state": "OPEN", "url": "https://x", '
        '"labels": [{"name": "bug"}, {"name": "p1"}]}]'
    )
    issues = parse_gh_issues(raw)
    assert issues == [
        {
            "number": 1,
            "title": "Bug",
            "state": "OPEN",
            "url": "https://x",
            "labels": ["bug", "p1"],
            "classification": "confirmado",
            "source": "github_issues",
        }
    ]


def test_parse_gh_issues_missing_optional_fields_default_safely():
    issues = parse_gh_issues('[{"number": 2}]')
    assert issues == [
        {
            "number": 2,
            "title": "",
            "state": "",
            "url": "",
            "labels": [],
            "classification": "confirmado",
            "source": "github_issues",
        }
    ]


def test_parse_gh_issues_ignores_non_dict_labels():
    issues = parse_gh_issues('[{"number": 3, "labels": ["raw-string-label", {"name": "ok"}]}]')
    assert issues[0]["labels"] == ["ok"]


def test_dedupe_facts_removes_exact_duplicates_by_composite_key():
    fact = {"classification": "confirmado", "claim": "x", "source": "y"}
    deduped = dedupe_facts([fact, dict(fact)])
    assert deduped == [fact]


def test_dedupe_facts_preserves_first_occurrence_order():
    a = {"classification": "confirmado", "claim": "a", "source": "s"}
    b = {"classification": "confirmado", "claim": "b", "source": "s"}
    deduped = dedupe_facts([a, b, dict(a)])
    assert deduped == [a, b]


def test_dedupe_facts_distinguishes_by_each_key_component():
    a = {"classification": "confirmado", "claim": "x", "source": "s1"}
    b = {"classification": "confirmado", "claim": "x", "source": "s2"}
    assert dedupe_facts([a, b]) == [a, b]


def test_dedupe_facts_empty_list_returns_empty_list():
    assert dedupe_facts([]) == []


def test_extract_github_repo_matches_ssh_remote():
    assert extract_github_repo("git@github.com:org/repo.git") == "org/repo"


def test_extract_github_repo_matches_https_remote():
    assert extract_github_repo("https://github.com/org/repo") == "org/repo"


def test_extract_github_repo_returns_empty_string_for_non_github_remote():
    assert extract_github_repo("https://gitlab.com/org/repo") == ""


def test_extract_github_repo_returns_empty_string_for_empty_input():
    assert extract_github_repo("") == ""
