# src/docs/application/corrections.py
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from docs.domain.corrections import parse_simple_yaml
from docs.domain.markdown_text import split_frontmatter
from docs.domain.ports.evidence_repository import EvidenceRepository
from docs.domain.ports.section_repository import SectionRepository
from docs.domain.sections import section_by_id


class CorrectionsService:
    def __init__(self, section_repository: SectionRepository, evidence_repository: EvidenceRepository) -> None:
        self.section_repository = section_repository
        self.evidence_repository = evidence_repository

    def apply_corrections(self, doc_id: str, config: dict[str, Any]) -> int:
        inbox = Path(config["paths"]["corrections_inbox_dir"])
        applied_path = Path(config["paths"]["corrections_applied"])
        applied_path.parent.mkdir(parents=True, exist_ok=True)
        if applied_path.exists():
            applied_state = json.loads(applied_path.read_text(encoding="utf-8"))
        else:
            applied_state = {"schema": 1, "applied": []}
        applied_ids = {item["id"] for item in applied_state.get("applied", [])}

        count = 0
        for correction_path in sorted(inbox.glob("*.yaml")) if inbox.exists() else []:
            correction = parse_simple_yaml(correction_path.read_text(encoding="utf-8"))
            correction_id = correction.get("id")
            if not correction_id or correction_id in applied_ids:
                continue
            section_id = correction.get("section_id", "")
            find = correction.get("find", "")
            replace = correction.get("replace", "")
            expected_hash = correction.get("expected_hash", "") or correction.get("expected_body_hash", "")
            if not section_id or not find:
                raise RuntimeError(f"Corrección inválida en {correction_path}: requiere id, section_id y find.")
            section = section_by_id(config["sections"], section_id)
            path = self.section_repository.section_path(doc_id, section["order"], section_id)
            if not path.exists():
                fallback = self.section_repository.find_section_file(doc_id, section_id)
                if fallback is not None:
                    path = fallback
                else:
                    raise FileNotFoundError(f"No existe sección para corrección {correction_id}: {path}")
            text = self.section_repository.read_raw_text(path)
            current_meta, current_body = split_frontmatter(text)
            current_hash = current_meta.get("body_hash") or self.evidence_repository.hash_text(current_body)
            if expected_hash and expected_hash != current_hash:
                raise RuntimeError(
                    f"Corrección {correction_id} esperaba hash {expected_hash}, pero la sección tiene {current_hash}."
                )
            if find not in text:
                raise RuntimeError(f"No se encontró texto objetivo para corrección {correction_id}: {find}")
            self.section_repository.write_raw_text(path, text.replace(find, replace, 1))
            applied_state.setdefault("applied", []).append(
                {
                    "id": correction_id,
                    "section_id": section_id,
                    "path": path.resolve().as_posix(),
                    "expected_hash": expected_hash,
                    "applied_at": datetime.now().isoformat(timespec="seconds"),
                }
            )
            applied_ids.add(correction_id)
            count += 1

        applied_path.write_text(json.dumps(applied_state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return count
