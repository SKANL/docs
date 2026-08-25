# src/docs/application/translate.py
"""Translate a PDF in place, preserving its layout.

The flow is: classify, read runs, group into blocks, translate each block
through the cache, fit the result back into the block's box, write, report.

Every compromise made along the way is COUNTED and returned, because a stage
that degrades where only a file can tell you reads as a clean success -- the
lesson `qa-docx` taught this repo after 24 silent runs. Font substitutions,
overflowed blocks, untranslated blocks and unverified pages all surface in the
command's own output line.

There is no content gate anywhere in this module, and there must never be one.
A model that declines degrades exactly one block; the document is still
written.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from docs.domain.block_grouping import group_runs_into_blocks
from docs.domain.ports.pdf_classify_port import PdfClassifyPort
from docs.domain.ports.pdf_text_edit_port import BlockReplacement, PdfTextEditPort
from docs.domain.ports.translation_memory_port import TranslationMemoryPort
from docs.domain.ports.translation_port import TranslationPort
from docs.domain.text_fitting import fit_text_to_block
from docs.domain.translation_guard import guarded_translate
from docs.domain.translation_memory_key import memory_key

# A text layer is what makes translation possible at all. `mixed` qualifies:
# it has one, even if some pages are images.
TRANSLATABLE_PDF_TYPES = frozenset({"text_based", "mixed"})

# Bumped only when the translation RULES change (terminology, tone, register),
# which must invalidate every cached entry rather than silently mixing old and
# new conventions in one document.
GLOSSARY_VERSION = "1"


class UntranslatablePdfError(RuntimeError):
    """Raised only when there is genuinely nothing to translate.

    This is NOT a refusal: it means the document has no text layer, so no
    engine could translate it either. The message names the remedy.
    """


@dataclass
class TranslateReport:
    output_path: Path
    blocks_total: int = 0
    blocks_translated: int = 0
    blocks_from_cache: int = 0
    blocks_overflowed: int = 0
    fonts_substituted: int = 0
    fonts_unrecognized: int = 0
    pages_untrusted: list[int] = field(default_factory=list)

    @property
    def blocks_untranslated(self) -> int:
        return self.blocks_total - self.blocks_translated

    def to_line(self) -> str:
        """One Spanish line for the CLI, naming every compromise made."""
        parts = [f"traducido: {self.blocks_translated}/{self.blocks_total} bloques"]
        if self.blocks_from_cache:
            parts.append(f"{self.blocks_from_cache} desde memoria")
        if self.blocks_untranslated:
            parts.append(f"{self.blocks_untranslated} sin traducir")
        if self.blocks_overflowed:
            parts.append(f"{self.blocks_overflowed} no entraron en su caja")
        if self.fonts_substituted:
            parts.append(f"{self.fonts_substituted} con fuente sustituida")
        if self.fonts_unrecognized:
            parts.append(f"{self.fonts_unrecognized} con familia no reconocida")
        if self.pages_untrusted:
            pages = ", ".join(str(page) for page in self.pages_untrusted)
            parts.append(f"paginas multicolumna sin verificar: {pages}")
        return "; ".join(parts)


class TranslateService:
    def __init__(
        self,
        classifier: PdfClassifyPort,
        editor: PdfTextEditPort,
        translator: TranslationPort,
        memory: TranslationMemoryPort,
    ) -> None:
        self._classifier = classifier
        self._editor = editor
        self._translator = translator
        self._memory = memory

    def translate_pdf(
        self, src: Path, out: Path, target_lang: str, source_lang: str = "auto"
    ) -> TranslateReport:
        classification = self._classifier.classify(src)
        if classification.pdf_type not in TRANSLATABLE_PDF_TYPES:
            raise UntranslatablePdfError(
                f"el PDF no tiene capa de texto (tipo: {classification.pdf_type}); "
                "se requiere OCR, que todavia no esta disponible"
            )

        report = TranslateReport(
            output_path=out, pages_untrusted=list(classification.pages_with_columns)
        )
        blocks = group_runs_into_blocks(self._editor.read_runs(src))
        report.blocks_total = len(blocks)

        replacements: list[BlockReplacement] = []
        for block in blocks:
            text, from_cache, ok = self._translate_block(block.text, source_lang, target_lang)
            report.blocks_translated += int(ok)
            report.blocks_from_cache += int(from_cache)
            fitted = fit_text_to_block(text, block)
            report.blocks_overflowed += int(fitted.overflowed)
            replacements.append(
                BlockReplacement(
                    page=block.page,
                    remove=block.runs,
                    fitted=fitted,
                    x=block.x,
                    top=block.top,
                )
            )

        write_report = self._editor.write_blocks(src, out, replacements)
        report.fonts_substituted = write_report.fonts_substituted
        report.fonts_unrecognized = write_report.fonts_unrecognized
        return report

    def _translate_block(
        self, text: str, source_lang: str, target_lang: str
    ) -> tuple[str, bool, bool]:
        """Returns (text_to_draw, came_from_cache, was_translated)."""
        key = memory_key(
            text, source_lang, target_lang, self._translator.engine_id, GLOSSARY_VERSION
        )
        cached = self._memory.get(key)
        if cached is not None:
            return cached, True, True

        outcome = guarded_translate(
            text,
            source_lang,
            target_lang,
            lambda value: self._translator.translate(value, source_lang, target_lang),
            # `getattr` rather than a bare attribute read: this is a
            # `Protocol`, and a test double or a third-party adapter written
            # before this attribute existed must keep working under the SAFE
            # default rather than raising.
            accept_unchanged=getattr(self._translator, "accepts_unchanged", False),
        )
        if outcome.translated:
            # Only a real translation is cached. Caching a pass-through would
            # make one bad run permanent for every future run of this document.
            self._memory.put(key, text, outcome.text)
        return outcome.text, False, outcome.translated
