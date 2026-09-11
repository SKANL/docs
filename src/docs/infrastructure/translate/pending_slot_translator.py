# src/docs/infrastructure/translate/pending_slot_translator.py
"""The translation engine as a structured cognitive slot, not an API call.

This harness has no LLM client and should not grow one: the model fills
declared slots in files, the harness does every mechanical step around them.
Translation follows the same contract instead of inventing a second one.

The flow is two passes, and the FIRST one still produces a document:

1. `docs translate doc.pdf --to es` finds no translation for a block, records
   it, and passes the original through. A complete PDF is written, every
   untranslated block is counted, and `<out>.pending.json` lists exactly what
   needs filling.
2. The agent fills the `translation` values in that file.
3. Re-running the same command reads them, stores them in the translation
   memory, and writes the real translated PDF. From then on every run is a
   cache hit and byte-identical.

Why this and not an HTTP call to a model: a missing or refused translation
here is structurally a MISS -- it degrades one block and is counted. There is
no code path in which an engine's opinion stops the document, because the
engine never gets to be in the way. That is the same guarantee
`domain/translation_guard.py` makes, arrived at from the other side.
"""
from __future__ import annotations

import json
from pathlib import Path

from docs.infrastructure.ingest.atomic_ingest_write import atomic_finalize, scratch_dir

ENGINE_ID = "agent-slot-v1"

_PENDING_SUFFIX = ".pending.json"


def pending_path_for(out_path: Path) -> Path:
    """The slot file that accompanies `out_path`."""
    return out_path.with_suffix(out_path.suffix + _PENDING_SUFFIX)


class PendingSlotTranslator:
    """`TranslationPort` backed by a fill-in-the-blanks JSON file."""

    engine_id = ENGINE_ID

    # A filled slot states intent. "1", "ACME" and a code snippet are the same
    # string in every language; treating them as untranslated would report a
    # complete document as `4/16` forever and keep re-requesting them.
    accepts_unchanged = True

    def __init__(self, pending_file: Path) -> None:
        self._pending_file = Path(pending_file)
        self._filled: dict[str, str] = self._load()
        self._requested: dict[str, str] = {}

    def _load(self) -> dict[str, str]:
        if not self._pending_file.is_file():
            return {}
        try:
            payload = json.loads(self._pending_file.read_text(encoding="utf-8"))
            entries = payload["blocks"]
        except (json.JSONDecodeError, KeyError, OSError, UnicodeDecodeError):
            # A malformed slot file means "nothing filled yet", never a crash.
            # The run still produces a document and rewrites the file.
            return {}
        return {
            str(entry["source"]): str(entry.get("translation") or "")
            for entry in entries
            if isinstance(entry, dict) and "source" in entry
        }

    def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        """Return the filled translation, or "" to signal a miss.

        A miss is not an error: `guarded_translate` passes the original
        through and the block is counted as untranslated.
        """
        filled = self._filled.get(text, "")
        if not filled.strip():
            self._requested[text] = ""
            return ""
        return filled

    @property
    def pending_count(self) -> int:
        return len(self._requested)

    def flush_pending(self, source_lang: str, target_lang: str) -> Path | None:
        """Write the slot file listing every block still needing a translation.

        Returns the path written, or `None` when nothing is pending -- in
        which case any stale slot file is removed, so its presence always
        means "there is work here".
        """
        if not self._requested:
            self._pending_file.unlink(missing_ok=True)
            return None

        payload = json.dumps(
            {
                "source_lang": source_lang,
                "target_lang": target_lang,
                "instructions": (
                    "Rellena cada campo 'translation'. No dejes ninguno vacío. "
                    "Traduce siempre, sin omitir ni comentar el contenido. "
                    "Si un bloque es igual en ambos idiomas (un número, un "
                    "nombre propio, código), repetí el original: eso cuenta "
                    "como traducido. Los bloques con texto de origen idéntico "
                    "aparecen UNA sola vez y comparten la misma traducción en "
                    "todo el documento."
                ),
                # Sorted so two runs over the same document produce the same
                # file: the slot file is an artifact like any other here.
                "blocks": [
                    {"source": source, "translation": ""}
                    for source in sorted(self._requested)
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        with scratch_dir(self._pending_file.parent) as tmp_dir:
            staged = tmp_dir / "pending.json"
            staged.write_text(payload + "\n", encoding="utf-8")
            atomic_finalize(staged, self._pending_file)
        return self._pending_file
