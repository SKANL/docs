from __future__ import annotations

from pathlib import Path

from docs.domain.ports.asset_repository import AssetRepository
from docs.domain.workspace import Workspace


class AssetService:
    def __init__(self, repository: AssetRepository, workspace: Workspace) -> None:
        self.repository = repository
        self.workspace = workspace

    def asset_path(self, doc_id: str, name: str) -> Path:
        safe = name if name.lower().endswith(".docx") else f"{name}.docx"
        return self.workspace.assets_dir(doc_id) / safe

    def add_asset(self, doc_id: str, src: str, name: str = "") -> Path:
        source = Path(src)
        if not self.repository.is_file(source):
            raise FileNotFoundError(f"No existe el archivo a adjuntar: {source}")
        if source.suffix.lower() != ".docx":
            raise ValueError(f"Sólo se admiten archivos .docx como asset: {source.name}")
        target_name = name or source.stem
        target = self.asset_path(doc_id, target_name)
        self.repository.ensure_dir(target.parent)
        self.repository.copy_file(source, target)
        return target

    def list_assets(self, doc_id: str) -> list[str]:
        directory = self.workspace.assets_dir(doc_id)
        if not self.repository.file_exists(directory):
            return []
        return [path.stem for path in self.repository.glob_docx(directory)]

    def remove_asset(self, doc_id: str, name: str) -> None:
        target = self.asset_path(doc_id, name)
        self.repository.remove_file(target)
