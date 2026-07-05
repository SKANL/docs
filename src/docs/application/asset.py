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

    def asset_path(self, doc_id: str, name: str, suffix: str | None = None) -> Path:
        known_extensions = self._allowed_extensions()
        if any(name.lower().endswith(ext) for ext in known_extensions):
            safe = name
        else:
            safe = f"{name}{suffix if suffix is not None else '.docx'}"
        return self.workspace.assets_dir(doc_id) / safe

    def add_asset(self, doc_id: str, src: str, name: str = "") -> Path:
        source = Path(src)
        if not self.repository.is_file(source):
            raise FileNotFoundError(f"No existe el archivo a adjuntar: {source}")
        suffix = source.suffix.lower()
        if suffix not in self._allowed_extensions():
            raise ValueError(f"Tipo de asset no permitido: {source.name} ({suffix or 'sin extensión'})")
        target_name = name or source.stem
        target = self.asset_path(doc_id, target_name, suffix=suffix)
        self.repository.ensure_dir(target.parent)
        self.repository.copy_file(source, target)
        return target

    def list_assets(self, doc_id: str, kind: str = "docx") -> list[str]:
        directory = self.workspace.assets_dir(doc_id)
        if not self.repository.file_exists(directory):
            return []
        extensions = self.asset_kinds.get(kind)
        if extensions is None:
            raise ValueError(f"Tipo de asset no configurado: {kind}")
        return [path.stem for path in self.repository.list_assets(directory, extensions)]

    def remove_asset(self, doc_id: str, name: str) -> None:
        target = self._resolve_remove_target(doc_id, name)
        self.repository.remove_file(target)

    def _resolve_remove_target(self, doc_id: str, name: str) -> Path:
        known_extensions = self._allowed_extensions()
        has_explicit_extension = any(name.lower().endswith(ext) for ext in known_extensions)
        if has_explicit_extension:
            return self.asset_path(doc_id, name)
        if len(self.asset_kinds) == 1:
            (only_extensions,) = self.asset_kinds.values()
            if len(only_extensions) == 1:
                return self.asset_path(doc_id, name, suffix=only_extensions[0])
        return self._resolve_ambiguous_stem(doc_id, name)

    def _resolve_ambiguous_stem(self, doc_id: str, name: str) -> Path:
        directory = self.workspace.assets_dir(doc_id)
        matches: list[Path] = []
        if self.repository.file_exists(directory):
            for extensions in self.asset_kinds.values():
                matches.extend(
                    path for path in self.repository.list_assets(directory, extensions) if path.stem == name
                )
        unique_matches = sorted(set(matches))
        if len(unique_matches) == 1:
            return unique_matches[0]
        if not unique_matches:
            example_ext = sorted(self._allowed_extensions())[0] if self._allowed_extensions() else ".docx"
            raise ValueError(
                f"No se encontró el asset `{name}` en ningún tipo configurado. "
                f"Especifique la extensión (por ejemplo, `{name}{example_ext}`)."
            )
        raise ValueError(
            f"El asset `{name}` existe en más de un tipo configurado. "
            "Especifique la extensión para eliminar el archivo correcto."
        )
