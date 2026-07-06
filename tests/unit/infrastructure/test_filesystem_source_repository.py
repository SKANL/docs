# tests/unit/infrastructure/test_filesystem_source_repository.py
import logging
import subprocess
from pathlib import Path

import pytest

from docs.infrastructure.persistence.filesystem_source_repository import FilesystemSourceRepository


@pytest.fixture
def repo() -> FilesystemSourceRepository:
    return FilesystemSourceRepository()


def test_glob_markdown_sorted(tmp_path: Path, repo):
    (tmp_path / "01-b.md").write_text("b")
    (tmp_path / "00-a.md").write_text("a")
    (tmp_path / "ignore.txt").write_text("x")
    files = repo.glob_markdown(tmp_path)
    assert [f.name for f in files] == ["00-a.md", "01-b.md"]


def test_read_context_texts_returns_empty_dict_when_dir_missing(tmp_path: Path, repo):
    assert repo.read_context_texts(tmp_path / "missing") == {}


def test_read_context_texts_skips_underscore_and_index_files(tmp_path: Path, repo):
    (tmp_path / "_draft.md").write_text("draft")
    (tmp_path / "index.md").write_text("index")
    (tmp_path / "scope.md").write_text("alcance del proyecto")
    texts = repo.read_context_texts(tmp_path)
    assert texts == {"scope": "alcance del proyecto"}


def test_read_context_texts_skips_curated_index_file(tmp_path: Path, repo):
    # Regression (fresh-context review CRITICAL, PR8 remediation): the new
    # progressive-disclosure `curated-index.md` (PR8's stage_build_context_index)
    # was not covered by this skip rule, so its body leaked into the fact-
    # detection text corpus scanned by `CollectionService.collect_sources`.
    (tmp_path / "scope.md").write_text("alcance del proyecto")
    (tmp_path / "curated-index.md").write_text("indice curado generado")
    texts = repo.read_context_texts(tmp_path)
    assert texts == {"scope": "alcance del proyecto"}


def test_glob_pattern_sorted_under_root(tmp_path: Path, repo):
    (tmp_path / "b.py").write_text("b")
    (tmp_path / "a.py").write_text("a")
    files = repo.glob_pattern(tmp_path, "*.py")
    assert [f.name for f in files] == ["a.py", "b.py"]


def test_find_executable_returns_none_for_unknown_binary(repo):
    assert repo.find_executable("definitely-not-a-real-binary-xyz") is None


def test_find_executable_resolves_known_binary_on_path(repo, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/git" if name == "git" else None)
    assert repo.find_executable("git") == "/usr/bin/git"


def test_run_gh_issue_list_invokes_expected_subprocess_args(repo, monkeypatch):
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args, 0, stdout="[]", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    result = repo.run_gh_issue_list("/usr/bin/gh", "owner/repo")
    assert result == "[]"
    assert captured["args"] == [
        "/usr/bin/gh", "issue", "list", "--repo", "owner/repo", "--state", "all",
        "--limit", "200", "--json", "number,title,state,createdAt,closedAt,labels,url",
    ]
    assert captured["kwargs"] == {
        "check": True, "capture_output": True, "text": True, "encoding": "utf-8",
    }


def test_run_gh_issue_list_propagates_called_process_error(repo, monkeypatch):
    def fake_run(args, **kwargs):
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr("subprocess.run", fake_run)
    with pytest.raises(subprocess.CalledProcessError):
        repo.run_gh_issue_list("/usr/bin/gh", "owner/repo")


def test_run_git_log_returns_stdout_on_success(tmp_path: Path, repo, monkeypatch):
    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout="abc123 commit message\n", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    target = tmp_path / "sub" / "file.py"
    result = repo.run_git_log(target, tmp_path)
    assert result == "abc123 commit message\n"


def test_run_git_log_returns_none_on_any_exception(tmp_path: Path, repo, monkeypatch):
    def fake_run(args, **kwargs):
        raise OSError("git not found")

    monkeypatch.setattr("subprocess.run", fake_run)
    assert repo.run_git_log(tmp_path / "file.py", tmp_path) is None


def test_run_git_log_logs_warning_on_any_exception(tmp_path: Path, repo, monkeypatch, caplog):
    def fake_run(args, **kwargs):
        raise OSError("git not found")

    monkeypatch.setattr("subprocess.run", fake_run)
    with caplog.at_level(logging.WARNING):
        repo.run_git_log(tmp_path / "file.py", tmp_path)
    assert any("git not found" in record.message for record in caplog.records)
    assert any(record.levelno == logging.WARNING for record in caplog.records)


def test_detect_github_remote_returns_stripped_stdout(tmp_path: Path, repo, monkeypatch):
    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout="git@github.com:org/repo.git\n", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    assert repo.detect_github_remote(tmp_path) == "git@github.com:org/repo.git"


def test_detect_github_remote_returns_empty_string_on_any_exception(tmp_path: Path, repo, monkeypatch):
    def fake_run(args, **kwargs):
        raise OSError("git not found")

    monkeypatch.setattr("subprocess.run", fake_run)
    assert repo.detect_github_remote(tmp_path) == ""


def test_detect_github_remote_logs_warning_on_any_exception(tmp_path: Path, repo, monkeypatch, caplog):
    def fake_run(args, **kwargs):
        raise OSError("git not found")

    monkeypatch.setattr("subprocess.run", fake_run)
    with caplog.at_level(logging.WARNING):
        repo.detect_github_remote(tmp_path)
    assert any("git not found" in record.message for record in caplog.records)
    assert any(record.levelno == logging.WARNING for record in caplog.records)


def test_run_git_rev_parse_head_returns_stripped_stdout(tmp_path: Path, repo, monkeypatch):
    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout="abc1234\n", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    assert repo.run_git_rev_parse_head(tmp_path) == "abc1234"


def test_run_git_rev_parse_head_returns_empty_string_on_any_exception(tmp_path: Path, repo, monkeypatch):
    def fake_run(args, **kwargs):
        raise OSError("git not found")

    monkeypatch.setattr("subprocess.run", fake_run)
    assert repo.run_git_rev_parse_head(tmp_path) == ""


def test_run_git_rev_parse_head_logs_warning_on_any_exception(tmp_path: Path, repo, monkeypatch, caplog):
    def fake_run(args, **kwargs):
        raise OSError("git not found")

    monkeypatch.setattr("subprocess.run", fake_run)
    with caplog.at_level(logging.WARNING):
        repo.run_git_rev_parse_head(tmp_path)
    assert any("git not found" in record.message for record in caplog.records)
    assert any(record.levelno == logging.WARNING for record in caplog.records)
