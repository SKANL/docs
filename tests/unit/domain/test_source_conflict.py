# tests/unit/domain/test_source_conflict.py
from docs.domain.source_conflict import detect_conflicts


def test_detect_conflicts_flags_two_sources_asserting_different_stack_members():
    sources = [
        ("proyecto.md", "El backend usa bun.js y TypeScript."),
        ("technical-design.md", "El backend está construido en PHP con Laravel."),
    ]

    conflicts = detect_conflicts(sources)

    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.group == "backend_runtime"
    assert conflict.members == ("node", "php")
    assert conflict.sources == ("proyecto.md", "technical-design.md")


def test_detect_conflicts_no_conflict_returns_empty_deterministic():
    sources = [
        ("a.md", "El backend usa Laravel para todo."),
        ("b.md", "La base de datos declarada es MySQL."),
    ]

    assert detect_conflicts(sources) == []


def test_detect_conflicts_single_source_mentioning_both_members_is_not_a_cross_source_conflict():
    sources = [("only.md", "Evaluamos Laravel y también bun.js antes de decidir.")]

    assert detect_conflicts(sources) == []


def test_detect_conflicts_output_sorted_regardless_of_input_order():
    sources_a = [
        ("z-source.md", "Usamos MongoDB."),
        ("a-source.md", "Usamos PostgreSQL."),
    ]
    sources_b = list(reversed(sources_a))

    result_a = detect_conflicts(sources_a)
    result_b = detect_conflicts(sources_b)

    assert result_a == result_b
    assert result_a[0].group == "database"
    assert result_a[0].members == ("mongodb", "postgresql")
    assert result_a[0].sources == ("a-source.md", "z-source.md")
