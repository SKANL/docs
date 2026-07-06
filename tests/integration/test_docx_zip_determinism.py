# tests/integration/test_docx_zip_determinism.py
from __future__ import annotations

import time as time_module
import zipfile
from pathlib import Path

from docx import Document

from docs.infrastructure.docx.deterministic_zip import SENTINEL_DATE_TIME
from docs.infrastructure.docx.python_docx_assembly_adapter import PythonDocxAssemblyAdapter


def _save_body_docx(tmp_path: Path, name: str = "body.docx") -> Path:
    document = Document()
    document.add_heading("Introduccion", level=1)
    document.add_paragraph("Texto de cuerpo.")
    path = tmp_path / name
    document.save(path)
    return path


def test_assemble_output_is_byte_identical_across_a_2_second_dos_timestamp_boundary(tmp_path, monkeypatch):
    # Root cause: python-docx's zip writer (`docx.opc.phys_pkg`) calls
    # `ZipFile.writestr(arcname, blob)` with no explicit `ZipInfo`, so
    # zipfile stamps every entry's `date_time` with `time.localtime(time.time())`
    # at the moment of the call -- 2-second DOS timestamp granularity. Two
    # builds of an otherwise identical document that straddle a 2-second
    # boundary produce a byte-level diff purely from zip metadata, violating
    # this harness's same-inputs -> byte-identical-outputs invariant. The
    # fixture body here (heading + plain paragraph, no bulleted list) mirrors
    # the real failure: no `w:numId` reference means
    # `ensure_bullet_numbering_part` takes its early-return, no-op path, so
    # nothing after `main.save(output_docx)` would otherwise touch the file.
    body = _save_body_docx(tmp_path)
    real_time = time_module.time

    def build(fixed_now: float, name: str) -> bytes:
        monkeypatch.setattr("time.time", lambda: fixed_now)
        try:
            output = tmp_path / name
            PythonDocxAssemblyAdapter().assemble(
                {}, body, output, cover_asset_path=None, embed_front_paths=[], embed_back_paths=[]
            )
            return output.read_bytes()
        finally:
            monkeypatch.setattr("time.time", real_time)

    t0 = real_time()
    first = build(t0, "first.docx")
    second = build(t0 + 2.5, "second.docx")  # straddles a 2-second DOS timestamp boundary

    assert first == second


def test_assemble_zip_entries_use_a_fixed_sentinel_timestamp(tmp_path, monkeypatch):
    body = _save_body_docx(tmp_path)
    output = tmp_path / "out.docx"
    PythonDocxAssemblyAdapter().assemble(
        {}, body, output, cover_asset_path=None, embed_front_paths=[], embed_back_paths=[]
    )
    with zipfile.ZipFile(output) as archive:
        timestamps = {info.date_time for info in archive.infolist()}
    assert timestamps == {(1980, 1, 1, 0, 0, 0)}


def test_assemble_embed_branch_normalizes_zip_timestamps_and_is_deterministic(tmp_path):
    # Coverage gap closed here (fresh-context review SUGGESTION, round 2): the
    # only two embed-branch tests in test_python_docx_assembly_adapter.py force
    # docxcompose to be unimportable, so they only exercise the RuntimeError
    # path. Nothing locked in the embed-branch SUCCESS path -- real
    # docxcompose.Composer, non-empty embed_front_paths/embed_back_paths,
    # composer.save(), then normalize_docx_zip_timestamps -- ever running.
    # docxcompose is a declared, always-installed dependency (pyproject.toml),
    # unlike pandoc/java, so no availability skip is needed here.
    body = _save_body_docx(tmp_path)
    front = Document()
    front.add_paragraph("FRONT MATTER MARKER")
    front_path = tmp_path / "front.docx"
    front.save(front_path)

    back = Document()
    back.add_paragraph("BACK MATTER MARKER")
    back_path = tmp_path / "back.docx"
    back.save(back_path)

    def build(name: str) -> bytes:
        output = tmp_path / name
        PythonDocxAssemblyAdapter().assemble(
            {},
            body,
            output,
            cover_asset_path=None,
            embed_front_paths=[front_path],
            embed_back_paths=[back_path],
        )
        return output.read_bytes()

    first = build("first.docx")
    second = build("second.docx")
    assert first == second

    with zipfile.ZipFile(tmp_path / "first.docx") as archive:
        timestamps = {info.date_time for info in archive.infolist()}
    assert timestamps == {SENTINEL_DATE_TIME}
