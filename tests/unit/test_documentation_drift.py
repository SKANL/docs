"""Drift guards for prose that describes the repo (CLAUDE.md, AGENTS.md, docs/, specs).

Each assertion pins a claim that was once false and is cheap to re-check.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".github" / "workflows"


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _prose(rel: str) -> str:
    return " ".join(_read(rel).split())


def test_agents_md_command_groups_match_the_cli():
    agents = _read("AGENTS.md")
    assert "| `docx` |" not in agents
    for group in ("source", "document", "workspace", "run"):
        assert f"| `{group}` |" in agents, group
    row = next(line for line in agents.splitlines() if line.startswith("| `doc` |"))
    assert "document publish" not in row


def test_agents_md_has_no_dangling_pipeline_sentence():
    assert "`docs document verify --json`. \nexisting callers." not in _read("AGENTS.md")


def test_test_files_cited_in_docs_exist():
    cited = set()
    for rel in ("CLAUDE.md", "AGENTS.md", "README.md", *(p.relative_to(REPO).as_posix() for p in (REPO / "docs").glob("*.md"))):
        cited |= set(re.findall(r"tests/[\w/]+\.py", _read(rel)))
    missing = sorted(p for p in cited if not (REPO / p).exists())
    assert not missing, missing


def test_ci_docs_job_names_match_workflows():
    jobs = {
        m.group(1)
        for path in WORKFLOWS.glob("*.yml")
        for m in re.finditer(r"(?m)^  ([a-z][\w-]*):\s*$", path.read_text(encoding="utf-8").split("jobs:", 1)[-1])
        if path.stem in {"quality", "toolchains", "architecture"}
    }
    ci = _read("docs/ci.md")
    for job in jobs:
        assert f"`{job}`" in ci, job
    claude = _prose("CLAUDE.md")
    assert "Nothing sets it yet" not in claude
    assert "no CI config" not in claude
    assert "fails if more than 2 tests skip" not in claude
    assert "pipeline <prep|ingest|assemble|all>" not in claude


def test_removed_pipeline_symbols_are_not_documented():
    for rel in ("openspec/specs/document-pipeline/spec.md", "openspec/specs/document-render/spec.md", "CLAUDE.md", "README.md"):
        text = _read(rel)
        for dead in ("pipeline_stage_plan", "domain/pipeline.py", "RunRecorder", "RunHistory", "RunReporter"):
            assert dead not in text, (rel, dead)
