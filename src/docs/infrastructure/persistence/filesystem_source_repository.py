# src/docs/infrastructure/persistence/filesystem_source_repository.py
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from docs.domain.context_index_files import is_context_content_filename

logger = logging.getLogger(__name__)


def _run_captured(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """One place that owns HOW this adapter shells out.

    Every call site wants the same four settings (check, captured output,
    text mode, UTF-8). Splatting them from a shared `dict[str, object]` hid
    the return type from the type checker at all four call sites; naming
    them once here keeps the single source of truth AND the typing.
    """
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8")



def _is_not_a_git_repo(exc: Exception) -> bool:
    """A non-git workspace (exit 128, `fatal: not a git repository ...`) is
    an EXPECTED, routine case for `run_git_rev_parse_head`/
    `detect_github_remote` -- every pipeline/verify/doctor run outside a
    repo hits it. Distinguishing it lets the caller log at DEBUG instead of
    WARNING, so the console isn't spammed on every command, while a
    genuinely unexpected git failure (missing binary, corrupt repo, ...)
    still WARNs -- git failures are surfaced, never silently swallowed."""
    if not isinstance(exc, subprocess.CalledProcessError):
        return False
    return "not a git repository" in (exc.stderr or "").lower()


class FilesystemSourceRepository:
    def glob_markdown(self, directory: Path) -> list[Path]:
        return sorted(directory.glob("*.md"))

    def read_context_texts(self, context_dir: Path) -> dict[str, str]:
        context: dict[str, str] = {}
        if not context_dir.exists():
            return context
        for path in sorted(context_dir.glob("*.md")):
            if not is_context_content_filename(path.name):
                continue
            context[path.stem] = path.read_text(encoding="utf-8")
        return context

    def glob_pattern(self, root: Path, pattern: str) -> list[Path]:
        return sorted(root.glob(pattern)) if pattern else []

    def find_executable(self, name: str) -> str | None:
        return shutil.which(name)

    def run_gh_issue_list(self, gh_path: str, repo: str) -> str:
        proc = _run_captured(
            [
                gh_path,
                "issue",
                "list",
                "--repo",
                repo,
                "--state",
                "all",
                "--limit",
                "200",
                "--json",
                "number,title,state,createdAt,closedAt,labels,url",
            ]
        )
        return proc.stdout

    def run_git_log(self, path: Path, repo_root: Path) -> str | None:
        try:
            proc = _run_captured(["git", "log", "--oneline", "--max-count=40", "--", str(path.relative_to(repo_root))], cwd=repo_root)
        except Exception as exc:
            logger.warning("git log failed for %s in %s: %s", path, repo_root, exc)
            return None
        return proc.stdout

    def detect_github_remote(self, repo_root: Path) -> str:
        try:
            proc = _run_captured(["git", "remote", "get-url", "origin"], cwd=repo_root)
        except Exception as exc:
            level = logging.DEBUG if _is_not_a_git_repo(exc) else logging.WARNING
            logger.log(level, "git remote get-url origin failed in %s: %s", repo_root, exc)
            return ""
        return proc.stdout.strip()

    def run_git_rev_parse_head(self, repo_root: Path) -> str:
        try:
            proc = _run_captured(["git", "rev-parse", "--short", "HEAD"], cwd=repo_root)
        except Exception as exc:
            level = logging.DEBUG if _is_not_a_git_repo(exc) else logging.WARNING
            logger.log(level, "git rev-parse --short HEAD failed in %s: %s", repo_root, exc)
            return ""
        return proc.stdout.strip()
