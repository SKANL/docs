# src/docs/infrastructure/persistence/filesystem_source_repository.py
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

_RUN_KWARGS = {"check": True, "capture_output": True, "text": True, "encoding": "utf-8"}
logger = logging.getLogger(__name__)


class FilesystemSourceRepository:
    def glob_markdown(self, directory: Path) -> list[Path]:
        return sorted(directory.glob("*.md"))

    def read_context_texts(self, context_dir: Path) -> dict[str, str]:
        context: dict[str, str] = {}
        if not context_dir.exists():
            return context
        for path in sorted(context_dir.glob("*.md")):
            if path.name.startswith("_") or path.name == "index.md":
                continue
            context[path.stem] = path.read_text(encoding="utf-8")
        return context

    def glob_pattern(self, root: Path, pattern: str) -> list[Path]:
        return sorted(root.glob(pattern)) if pattern else []

    def find_executable(self, name: str) -> str | None:
        return shutil.which(name)

    def run_gh_issue_list(self, gh_path: str, repo: str) -> str:
        proc = subprocess.run(
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
            ],
            **_RUN_KWARGS,
        )
        return proc.stdout

    def run_git_log(self, path: Path, repo_root: Path) -> str | None:
        try:
            proc = subprocess.run(
                ["git", "log", "--oneline", "--max-count=40", "--", str(path.relative_to(repo_root))],
                cwd=repo_root,
                **_RUN_KWARGS,
            )
        except Exception as exc:
            logger.warning("git log failed for %s in %s: %s", path, repo_root, exc)
            return None
        return proc.stdout

    def detect_github_remote(self, repo_root: Path) -> str:
        try:
            proc = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=repo_root,
                **_RUN_KWARGS,
            )
        except Exception as exc:
            logger.warning("git remote get-url origin failed in %s: %s", repo_root, exc)
            return ""
        return proc.stdout.strip()

    def run_git_rev_parse_head(self, repo_root: Path) -> str:
        try:
            proc = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=repo_root,
                **_RUN_KWARGS,
            )
        except Exception as exc:
            logger.warning("git rev-parse --short HEAD failed in %s: %s", repo_root, exc)
            return ""
        return proc.stdout.strip()
