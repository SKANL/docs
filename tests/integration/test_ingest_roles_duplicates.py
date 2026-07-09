# tests/integration/test_ingest_roles_duplicates.py
"""Front D (source-role classification) + Front E (near-duplicate
detection) wired into `IngestService.ingest_inbox` (design.md Decisions 4
and 5; spec: document-ingest "Source-Role Classification" / "Near-Duplicate
Detection"). The classification queue (`inbox/_classification-queue.json`)
is the interface where EXTERNAL confirmation enters -- the harness only
proposes, deterministically; a human/agent confirms by editing the queue
file; the confirmation round-trips into `_source-manifest.json` on the next
scan. Near-duplicate decisions are similarly reversible by editing the
manifest's own `duplicates` entries."""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path

from docs.application.ingest import IngestService


def _strip_accents(text: str) -> str:
    """Test-local accent stripper, deliberately INDEPENDENT from
    production code -- see tests/unit/domain/test_near_duplicate.py's
    identical helper (fresh-context verify, PR4 fix batch, CRITICAL-1)."""
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


class _FakeDetector:
    def __init__(self, kind_by_name: dict[str, str]) -> None:
        self.kind_by_name = kind_by_name

    def detect(self, path: Path) -> str:
        return self.kind_by_name.get(path.name, "")


class _TextEchoHandler:
    """Writes the SOURCE's own bytes as the ingested markdown output --
    real enough for near-duplicate detection (which reads output content),
    following the real `<stem>-<kind>-<sha8>.md` naming convention."""

    def ingest(self, src: Path, out_dir: Path, kind: str) -> Path:
        import hashlib

        sha8 = hashlib.sha256(src.read_bytes()).hexdigest()[:8]
        target = out_dir / f"{src.stem}-{kind}-{sha8}.md"
        target.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        return target


def _service(kind_by_name: dict[str, str]) -> IngestService:
    return IngestService(_FakeDetector(kind_by_name), {"md": _TextEchoHandler(), "pdf": _TextEchoHandler()})


# --- 8.4/8.5: classification queue + source-manifest wiring --------------


def test_classification_queue_is_written_keyed_by_relative_path(tmp_path: Path):
    inbox = tmp_path / "inbox"
    (inbox / "normativa").mkdir(parents=True)
    (inbox / "normativa" / "reglas.md").write_text("Contenido normativo.", encoding="utf-8")
    service = _service({"reglas.md": "md"})

    service.ingest_inbox(inbox, tmp_path / "sections")

    queue_path = inbox / "_classification-queue.json"
    assert queue_path.exists()
    payload = json.loads(queue_path.read_text(encoding="utf-8"))
    assert payload["schema"] == 1
    entry = payload["entries"]["normativa/reglas.md"]
    assert entry["proposed_role"] == "normative"
    assert entry["confidence"] == "high"
    # Both folder ("normativa") AND filename ("reglas") carry the normative
    # signal here -- a representative real-world case where both agree.
    assert entry["signals"] == ["folder:normativa", "filename:reglas"]
    assert entry["confirmed_role"] is None


def test_classification_queue_determinism_two_runs_byte_identical(tmp_path: Path):
    inbox = tmp_path / "inbox"
    (inbox / "normativa").mkdir(parents=True)
    (inbox / "ejemplos").mkdir(parents=True)
    (inbox / "normativa" / "reglas.md").write_text("Contenido normativo.", encoding="utf-8")
    (inbox / "ejemplos" / "muestra.md").write_text("Contenido de muestra.", encoding="utf-8")

    _service({"reglas.md": "md", "muestra.md": "md"}).ingest_inbox(inbox, tmp_path / "sections")
    first_bytes = (inbox / "_classification-queue.json").read_bytes()

    _service({"reglas.md": "md", "muestra.md": "md"}).ingest_inbox(inbox, tmp_path / "sections")
    second_bytes = (inbox / "_classification-queue.json").read_bytes()

    assert first_bytes == second_bytes
    assert b"generated_at" not in first_bytes


def test_source_manifest_carries_proposed_role_fields(tmp_path: Path):
    inbox = tmp_path / "inbox"
    (inbox / "evidencia").mkdir(parents=True)
    (inbox / "evidencia" / "captura.md").write_text("Evidencia recopilada.", encoding="utf-8")
    service = _service({"captura.md": "md"})

    service.ingest_inbox(inbox, tmp_path / "sections")

    manifest = json.loads((inbox / "_source-manifest.json").read_text(encoding="utf-8"))
    entry = next(s for s in manifest["sources"] if s["relative_path"] == "evidencia/captura.md")
    assert entry["proposed_role"] == "evidence"
    assert entry["confidence"] == "high"
    assert entry["confirmed_role"] is None


def test_confirmed_role_in_queue_round_trips_into_manifest_on_next_scan(tmp_path: Path):
    # spec: "Confirmed role recorded and enforced" -- an agent edits the
    # QUEUE file (the interface where external confirmation enters); the
    # NEXT scan reads that confirmation and merges it into the manifest,
    # while also preserving it in the freshly-rewritten queue.
    inbox = tmp_path / "inbox"
    (inbox / "misc").mkdir(parents=True)
    (inbox / "misc" / "unclear.md").write_text("Contenido ambiguo sin señal clara.", encoding="utf-8")
    service = _service({"unclear.md": "md"})
    service.ingest_inbox(inbox, tmp_path / "sections")

    queue_path = inbox / "_classification-queue.json"
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    assert queue["entries"]["misc/unclear.md"]["proposed_role"] == "unknown"
    queue["entries"]["misc/unclear.md"]["confirmed_role"] = "normative"
    queue_path.write_text(json.dumps(queue), encoding="utf-8")

    service.ingest_inbox(inbox, tmp_path / "sections")

    manifest = json.loads((inbox / "_source-manifest.json").read_text(encoding="utf-8"))
    entry = next(s for s in manifest["sources"] if s["relative_path"] == "misc/unclear.md")
    assert entry["confirmed_role"] == "normative"
    second_queue = json.loads(queue_path.read_text(encoding="utf-8"))
    assert second_queue["entries"]["misc/unclear.md"]["confirmed_role"] == "normative"


# --- 8.6: role gating (draft admits with gap, strict blocks) ------------


def test_unconfirmed_role_admitted_with_pendiente_gap_in_draft_mode(tmp_path: Path):
    inbox = tmp_path / "inbox"
    (inbox / "normativa").mkdir(parents=True)
    (inbox / "normativa" / "reglas.md").write_text("Contenido normativo.", encoding="utf-8")
    service = _service({"reglas.md": "md"})

    service.ingest_inbox(inbox, tmp_path / "sections", strict=False)

    manifest = json.loads((inbox / "_source-manifest.json").read_text(encoding="utf-8"))
    entry = next(s for s in manifest["sources"] if s["relative_path"] == "normativa/reglas.md")
    assert entry["role_status"]["blocked"] is False
    assert entry["role_status"]["effective_role"] == "normative"
    assert "PENDIENTE" in entry["role_status"]["gap"]


def test_unconfirmed_role_blocks_in_strict_mode(tmp_path: Path):
    inbox = tmp_path / "inbox"
    (inbox / "normativa").mkdir(parents=True)
    (inbox / "normativa" / "reglas.md").write_text("Contenido normativo.", encoding="utf-8")
    service = _service({"reglas.md": "md"})

    service.ingest_inbox(inbox, tmp_path / "sections", strict=True)

    manifest = json.loads((inbox / "_source-manifest.json").read_text(encoding="utf-8"))
    entry = next(s for s in manifest["sources"] if s["relative_path"] == "normativa/reglas.md")
    assert entry["role_status"]["blocked"] is True
    assert entry["role_status"]["effective_role"] is None


def test_confirmed_role_routes_source_correctly_in_strict_mode(tmp_path: Path):
    inbox = tmp_path / "inbox"
    (inbox / "misc").mkdir(parents=True)
    (inbox / "misc" / "doc.md").write_text("Contenido sin señal.", encoding="utf-8")
    service = _service({"doc.md": "md"})
    service.ingest_inbox(inbox, tmp_path / "sections")
    queue_path = inbox / "_classification-queue.json"
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    queue["entries"]["misc/doc.md"]["confirmed_role"] = "evidence"
    queue_path.write_text(json.dumps(queue), encoding="utf-8")

    service.ingest_inbox(inbox, tmp_path / "sections", strict=True)

    manifest = json.loads((inbox / "_source-manifest.json").read_text(encoding="utf-8"))
    entry = next(s for s in manifest["sources"] if s["relative_path"] == "misc/doc.md")
    assert entry["role_status"]["blocked"] is False
    assert entry["role_status"]["effective_role"] == "evidence"


# --- 9.4/9.5: near-duplicate detection wired post-ingest -----------------


def test_near_duplicate_pass_records_kept_and_superseded_in_manifest(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    text = "Contenido idéntico entre la copia curada y la copia extraída del PDF original y más texto de relleno."
    (inbox / "curated.md").write_text(text, encoding="utf-8")
    (inbox / "extracted.pdf").write_text(text, encoding="utf-8")
    service = _service({"curated.md": "md", "extracted.pdf": "pdf"})

    report = service.ingest_inbox(inbox, tmp_path / "sections")
    assert report["processed"] == 2

    manifest = json.loads((inbox / "_source-manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["duplicates"]) == 1
    decision = manifest["duplicates"][0]
    assert decision["kept"] == "curated.md"
    assert decision["superseded"] == "extracted.pdf"
    assert decision["jaccard"] == 1.0
    assert "near-duplicate" in decision["reason"]


def test_near_duplicate_decision_is_reversible_by_editing_the_manifest(tmp_path: Path):
    # spec: "Duplicate decision is reversible" -- editing the manifest entry
    # to reverse kept/superseded makes the previously suppressed source
    # active on the next run.
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    text = "Contenido idéntico entre la copia curada y la copia extraída del PDF original y más texto de relleno."
    (inbox / "curated.md").write_text(text, encoding="utf-8")
    (inbox / "extracted.pdf").write_text(text, encoding="utf-8")
    service = _service({"curated.md": "md", "extracted.pdf": "pdf"})
    service.ingest_inbox(inbox, tmp_path / "sections")

    manifest_path = inbox / "_source-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["duplicates"][0]["kept"] == "curated.md"
    manifest["duplicates"][0]["kept"] = "extracted.pdf"
    manifest["duplicates"][0]["superseded"] = "curated.md"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    service.ingest_inbox(inbox, tmp_path / "sections")

    second_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    decision = second_manifest["duplicates"][0]
    assert decision["kept"] == "extracted.pdf"
    assert decision["superseded"] == "curated.md"


def test_distinct_sources_are_not_falsely_merged_in_manifest(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "a.md").write_text("Un tema completamente distinto sobre cocina y gastronomía regional.", encoding="utf-8")
    (inbox / "b.md").write_text("Un tema completamente distinto sobre astronomía y cuerpos celestes.", encoding="utf-8")
    service = _service({"a.md": "md", "b.md": "md"})

    service.ingest_inbox(inbox, tmp_path / "sections")

    manifest = json.loads((inbox / "_source-manifest.json").read_text(encoding="utf-8"))
    assert manifest["duplicates"] == []


# --- determinism closeout (8.7 / 9.6) -------------------------------------


def test_source_manifest_with_roles_and_duplicates_is_byte_stable_across_two_runs(
    tmp_path: Path,
):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "normativa").mkdir()
    (inbox / "normativa" / "reglas.md").write_text("Contenido normativo con suficiente longitud de texto.", encoding="utf-8")
    text = "Contenido idéntico entre la copia curada y la copia extraída del PDF original y más texto de relleno."
    (inbox / "curated.md").write_text(text, encoding="utf-8")
    (inbox / "extracted.pdf").write_text(text, encoding="utf-8")
    kind_by_name = {"reglas.md": "md", "curated.md": "md", "extracted.pdf": "pdf"}

    # Warm-up run: the very FIRST scan legitimately differs from every
    # subsequent one (status "ingested" vs "skipped" once outputs already
    # exist -- same convergence caveat as Front C's own determinism test).
    # Determinism is compared from the SECOND scan onward.
    _service(kind_by_name).ingest_inbox(inbox, tmp_path / "sections")

    _service(kind_by_name).ingest_inbox(inbox, tmp_path / "sections")
    first = (inbox / "_source-manifest.json").read_bytes()

    _service(kind_by_name).ingest_inbox(inbox, tmp_path / "sections")
    second = (inbox / "_source-manifest.json").read_bytes()

    assert first == second
    assert b"generated_at" not in first


# --- Realistic acceptance shape (real-world drop, fixture not real files) -


def test_realistic_drop_shape_roles_and_near_duplicate_all_recorded_nothing_silent(
    tmp_path: Path,
):
    # Acceptance context: mirrors the shape of a real user's OneDrive inbox
    # drop -- guides/manual-estadia-tic/ (normative, folder signal),
    # example_tesina/RE-Ejemplo.pdf (example, folder+filename signal), and a
    # near-duplicate pair (extracted/GUIA-Estadia.md vs
    # guides/GUIA-Estadia.pdf -- same guide, MD is the curated
    # higher-fidelity copy). Fixture tree, never the user's actual files.
    #
    # CRITICAL-1 fix-batch honesty requirement (fresh-context verify): the
    # two GUIA variants are GENUINELY DIFFERENT text, not the same string
    # written twice -- guide_curated has correct Spanish accents (as a
    # hand-curated markdown file would); guide_extracted is independently
    # derived with accents stripped PLUS markdown structural noise (as a
    # plausible PDF-extraction artifact), so this test can only pass with
    # REAL accent/markup normalization, not by accident.
    inbox = tmp_path / "inbox"
    manual_dir = inbox / "guides" / "manual-estadia-tic"
    manual_dir.mkdir(parents=True)
    (manual_dir / "00-intro.md").write_text(
        "Introducción al manual normativo de estadía técnica institucional.",
        encoding="utf-8",
    )

    example_dir = inbox / "example_tesina"
    example_dir.mkdir(parents=True)
    (example_dir / "RE-Ejemplo.pdf").write_text(
        "Contenido de ejemplo estructural usado como referencia de formato.",
        encoding="utf-8",
    )

    guide_words = (
        "Guía de referencia para la elaboración del reporte de estadía técnica "
        "en organizaciones receptoras y demás actores relevantes del proceso "
        "académico institucional de vinculación profesional y sus programas "
        "correspondientes de formación técnica reconocidos oficialmente"
    ).split()
    guide_curated = " ".join(guide_words)
    extracted_words = [_strip_accents(word) for word in guide_words]
    guide_extracted = "# " + " ".join(extracted_words)
    guide_extracted = guide_extracted.replace("tecnica", "**tecnica**", 1)

    (inbox / "extracted").mkdir(parents=True)
    (inbox / "extracted" / "GUIA-Estadia.md").write_text(guide_curated, encoding="utf-8")
    (inbox / "guides" / "GUIA-Estadia.pdf").write_text(guide_extracted, encoding="utf-8")

    kind_by_name = {
        "00-intro.md": "md",
        "RE-Ejemplo.pdf": "pdf",
        "GUIA-Estadia.md": "md",
        "GUIA-Estadia.pdf": "pdf",
    }
    service = _service(kind_by_name)

    report = service.ingest_inbox(inbox, tmp_path / "sections")

    # Nothing silent: every dropped file appears with a decisive status.
    assert report["ignored"] == []
    assert all(e.get("status") != "error" for e in report["files"])

    manifest = json.loads((inbox / "_source-manifest.json").read_text(encoding="utf-8"))
    by_rel = {s["relative_path"]: s for s in manifest["sources"]}

    # Roles proposed correctly from folder/filename signals.
    manual_entry = by_rel["guides/manual-estadia-tic/00-intro.md"]
    assert manual_entry["proposed_role"] == "normative"
    assert manual_entry["confidence"] == "high"
    example_entry = by_rel["example_tesina/RE-Ejemplo.pdf"]
    assert example_entry["proposed_role"] == "example"

    # The PDF/MD near-dup is detected, MD (curated) preferred.
    assert len(manifest["duplicates"]) == 1
    decision = manifest["duplicates"][0]
    assert decision["kept"] == "extracted/GUIA-Estadia.md"
    assert decision["superseded"] == "guides/GUIA-Estadia.pdf"
    assert decision["jaccard"] >= 0.85

    # Everything queued for external confirmation, keyed by relative_path.
    queue = json.loads((inbox / "_classification-queue.json").read_text(encoding="utf-8"))
    assert set(queue["entries"]) == set(by_rel)
