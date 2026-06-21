from __future__ import annotations

import shutil
from pathlib import Path


class FilesystemAssetRepository:
    def ensure_dir(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)

    def is_file(self, path: Path) -> bool:
        return path.exists() and path.is_file()

    def copy_file(self, src: Path, dest: Path) -> None:
        shutil.copy2(src, dest)

    def glob_docx(self, directory: Path) -> list[Path]:
        return sorted(directory.glob("*.docx"))

    def remove_file(self, path: Path) -> None:
        if path.exists():
            path.unlink()

    def file_exists(self, path: Path) -> bool:
        return path.exists()
