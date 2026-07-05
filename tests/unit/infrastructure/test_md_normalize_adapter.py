# tests/unit/infrastructure/test_md_normalize_adapter.py
"""`SourceIngestPort` implementation for md/txt sources: reuse
`split_frontmatter` to normalize frontmatter and produce conformant
Markdown (document-ingest spec: `Type-Based Ingest Routing` scenario
"Markdown/TXT normalized")."""
from pathlib import Path

from docs.infrastructure.ingest.md_normalize_adapter import MdNormalizeAdapter


def test_md_source_with_json_frontmatter_is_reformatted_canonically(tmp_path: Path):
    src = tmp_path / "notes.md"
    src.write_text('---\n{"b": 2, "a": 1}\n---\nBody text.\n', encoding="utf-8")
    out_dir = tmp_path / "ingested"
    out_dir.mkdir()
    adapter = MdNormalizeAdapter()

    output = adapter.ingest(src, out_dir, "md")

    assert output.exists()
    assert output.parent == out_dir
    assert output.name.startswith("notes-md-")
    text = output.read_text(encoding="utf-8")
    assert text.index('"a": 1') < text.index('"b": 2'), "keys must be sorted deterministically"
    assert text.endswith("Body text.\n")


def test_md_source_without_frontmatter_passes_body_through_unchanged(tmp_path: Path):
    src = tmp_path / "plain.md"
    src.write_text("# Heading\n\nJust content.\n", encoding="utf-8")
    out_dir = tmp_path / "ingested"
    out_dir.mkdir()
    adapter = MdNormalizeAdapter()

    output = adapter.ingest(src, out_dir, "md")

    assert output.read_text(encoding="utf-8") == "# Heading\n\nJust content.\n"


def test_txt_source_uses_txt_kind_in_output_name(tmp_path: Path):
    src = tmp_path / "readme.txt"
    src.write_text("Just plain text, no frontmatter.\n", encoding="utf-8")
    out_dir = tmp_path / "ingested"
    out_dir.mkdir()
    adapter = MdNormalizeAdapter()

    output = adapter.ingest(src, out_dir, "txt")

    assert output.name.startswith("readme-txt-")
    assert output.read_text(encoding="utf-8") == "Just plain text, no frontmatter.\n"


def test_output_naming_uses_passed_kind_not_source_extension(tmp_path: Path):
    # FRESH-REVIEW FINDING 1 unit-level check: identity must come from the
    # `kind` IngestService passes in (the detector-resolved value), not be
    # re-derived from the source's own extension — a source named
    # `readme.txt` whose detected kind is "md" must be named with "md".
    src = tmp_path / "readme.txt"
    src.write_text("Body only, no frontmatter.\n", encoding="utf-8")
    out_dir = tmp_path / "ingested"
    out_dir.mkdir()
    adapter = MdNormalizeAdapter()

    output = adapter.ingest(src, out_dir, "md")

    assert output.name.startswith("readme-md-")


def test_malformed_frontmatter_falls_back_to_raw_text_unchanged(tmp_path: Path):
    # Mirrors split_frontmatter's own fallback: an unclosed or invalid-JSON
    # frontmatter block is not silently dropped or corrupted — the whole
    # raw text passes through untouched.
    src = tmp_path / "broken.md"
    raw = "---\nnot valid json\n---\nBody.\n"
    src.write_text(raw, encoding="utf-8")
    out_dir = tmp_path / "ingested"
    out_dir.mkdir()
    adapter = MdNormalizeAdapter()

    output = adapter.ingest(src, out_dir, "md")

    assert output.read_text(encoding="utf-8") == raw


def test_reingesting_unchanged_source_produces_byte_identical_output(tmp_path: Path):
    src = tmp_path / "notes.md"
    src.write_text('---\n{"z": 1, "a": 2}\n---\nContent.\n', encoding="utf-8")
    out_dir = tmp_path / "ingested"
    out_dir.mkdir()
    adapter = MdNormalizeAdapter()

    first = adapter.ingest(src, out_dir, "md")
    first_bytes = first.read_bytes()
    # Second adapter instance, simulating a fresh process run.
    second = MdNormalizeAdapter().ingest(src, tmp_path / "ingested2", "md")

    assert second.read_bytes() == first_bytes
