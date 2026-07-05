from __future__ import annotations

from pathlib import Path

from docs.domain.ports.asset_repository import AssetRepository
from docs.domain.workspace import Workspace

# Default asset-kind configuration: kind name -> allowed extensions (with dot).
# Preserves prior DOCX-only behavior when no configuration is supplied.
_DEFAULT_ASSET_KINDS: dict[str, tuple[str, ...]] = {"docx": (".docx",)}


class AssetService:
    def __init__(
        self,
        repository: AssetRepository,
        workspace: Workspace,
        asset_kinds: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        self.repository = repository
        self.workspace = workspace
        self.asset_kinds = dict(asset_kinds) if asset_kinds is not None else dict(_DEFAULT_ASSET_KINDS)

    def _allowed_extensions(self) -> set[str]:
        allowed: set[str] = set()
        for extensions in self.asset_kinds.values():
            allowed.update(extensions)
        return allowed

    def asset_path(self, doc_id: str, name: str) -> Path:
        safe = name if name.lower().endswith(".docx") else f"{name}.docx"
        return self.workspace.assets_dir(doc_id) / safe

    def add_asset(self, doc_id: str, src: str, name: str = "") -> Path:
        source = Path(src)
        if not self.repository.is_file(source):
            raise FileNotFoundError(f"No existe el archivo a adjuntar: {source}")
        suffix = source.suffix.lower()
        if suffix not in self._allowed_extensions():
            raise ValueError(f"Tipo de asset no permitido: {source.name} ({suffix or 'sin extensión'})")
        target_name = name or source.stem
        target = self.asset_path(doc_id, target_name)
        self.repository.ensure_dir(target.parent)
        self.repository.copy_file(source, target)
        return target

    def list_assets(self, doc_id: str, kind: str = "docx") -> list[str]:
        directory = self.workspace.assets_dir(doc_id)
        if not self.repository.file_exists(directory):
            return []
        return [path.stem for path in self.repository.list_assets(directory, kind)]

    def remove_asset(self, doc_id: str, name: str) -> None:
        target = self.asset_path(doc_id, name)
        self.repository.remove_file(target)
