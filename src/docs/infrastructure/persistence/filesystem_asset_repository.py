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

    def list_assets(self, directory: Path, extensions: tuple[str, ...]) -> list[Path]:
        matches: set[Path] = set()
        for ext in extensions:
            pattern = ext if ext.startswith(".") else f".{ext}"
            matches.update(directory.glob(f"*{pattern}"))
        return sorted(matches)

    def remove_file(self, path: Path) -> None:
        if path.exists():
            path.unlink()

    def file_exists(self, path: Path) -> bool:
        return path.exists()
