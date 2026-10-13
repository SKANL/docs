from pathlib import Path

from docs.domain.translation_sidecars import translation_sidecars
from docs.infrastructure.translate.pending_slot_translator import pending_path_for


def test_sidecars_live_beside_the_output_and_agree_with_the_adapter():
    out = Path("x") / "book.en.pdf"
    memory_dir, pending = translation_sidecars(out)
    assert memory_dir == Path("x") / "translations"
    assert pending == Path("x") / "book.en.pdf.pending.json" == pending_path_for(out)
