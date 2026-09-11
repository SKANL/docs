import json

import pytest
from typer.testing import CliRunner

from docs.cli.main import app

runner = CliRunner()


@pytest.fixture
def sample_pdf(tmp_path):
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("pdf")
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=(6, 4))
    fig.text(0.1, 0.8, "Hello world", fontsize=18)
    fig.text(0.1, 0.5, "Second line of text", fontsize=12)
    path = tmp_path / "doc.pdf"
    fig.savefig(path)
    plt.close(fig)
    return path


def test_the_command_is_registered_with_help_text():
    result = runner.invoke(app, ["translate", "--help"])
    assert result.exit_code == 0
    assert "--to" in result.output


def test_a_missing_input_file_fails_with_a_spanish_message(tmp_path):
    result = runner.invoke(app, ["translate", str(tmp_path / "nope.pdf"), "--to", "es"])
    assert result.exit_code != 0
    assert "no existe" in result.output.lower()


def test_the_target_language_is_required(sample_pdf):
    assert runner.invoke(app, ["translate", str(sample_pdf)]).exit_code != 0


def test_the_first_run_writes_a_document_and_a_pending_slot_file(sample_pdf, tmp_path):
    out = tmp_path / "out.pdf"
    result = runner.invoke(app, ["translate", str(sample_pdf), "--to", "es", "--output", str(out)])
    assert result.exit_code == 0, result.output
    assert out.exists(), "a first run must still produce a complete document"
    pending = tmp_path / "out.pdf.pending.json"
    assert pending.exists()
    blocks = json.loads(pending.read_text(encoding="utf-8"))["blocks"]
    assert [b["source"] for b in blocks] == sorted(b["source"] for b in blocks)
    assert all(b["translation"] == "" for b in blocks)


def test_filling_the_slot_file_translates_on_the_second_run(sample_pdf, tmp_path):
    out = tmp_path / "out.pdf"
    runner.invoke(app, ["translate", str(sample_pdf), "--to", "es", "--output", str(out)])

    pending = tmp_path / "out.pdf.pending.json"
    payload = json.loads(pending.read_text(encoding="utf-8"))
    for block in payload["blocks"]:
        payload_text = block["source"]
        block["translation"] = f"ES::{payload_text}"
    pending.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    result = runner.invoke(app, ["translate", str(sample_pdf), "--to", "es", "--output", str(out)])
    assert result.exit_code == 0, result.output
    assert "0 sin traducir" not in result.output
    assert not pending.exists(), "nothing pending means the slot file must be gone"
    assert (tmp_path / "translations").is_dir(), "translations must land in the memory"


def test_the_third_run_is_byte_identical_to_the_second(sample_pdf, tmp_path):
    out = tmp_path / "out.pdf"
    runner.invoke(app, ["translate", str(sample_pdf), "--to", "es", "--output", str(out)])
    pending = tmp_path / "out.pdf.pending.json"
    payload = json.loads(pending.read_text(encoding="utf-8"))
    for block in payload["blocks"]:
        block["translation"] = f"ES::{block['source']}"
    pending.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    runner.invoke(app, ["translate", str(sample_pdf), "--to", "es", "--output", str(out)])
    second = out.read_bytes()
    runner.invoke(app, ["translate", str(sample_pdf), "--to", "es", "--output", str(out)])
    assert out.read_bytes() == second, "a warm cache must reproduce identical bytes"


def test_the_output_line_reports_what_was_not_translated(sample_pdf, tmp_path):
    out = tmp_path / "out.pdf"
    result = runner.invoke(app, ["translate", str(sample_pdf), "--to", "es", "--output", str(out)])
    assert "sin traducir" in result.output
    assert "Pendiente:" in result.output


def test_the_default_output_name_carries_the_target_language(sample_pdf):
    result = runner.invoke(app, ["translate", str(sample_pdf), "--to", "pt"])
    assert result.exit_code == 0, result.output
    assert sample_pdf.with_name("doc.pt.pdf").exists()


def test_identical_blocks_share_one_translation(tmp_path):
    """A DELIBERATE decision, pinned here so it cannot drift into a bug report.

    The translation memory is content-addressed, and that is precisely what
    makes reruns byte-identical. The consequence is that a source string
    appearing twice is asked for once and translated the same way in both
    places -- which is also correct: the same heading rendered two different
    ways in one document is an inconsistency, not richness.

    The cost, stated rather than hidden: a string that legitimately needs
    different translations in different contexts cannot get them. That is the
    known limitation of every translation memory, and segment context is the
    upgrade path, not a reason to translate the same text twice.
    """
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("pdf")
    import matplotlib.pyplot as plt

    figure = plt.figure(figsize=(6, 4))
    figure.text(0.1, 0.80, "Total", fontsize=12)
    figure.text(0.1, 0.40, "Total", fontsize=12)
    src = tmp_path / "dup.pdf"
    figure.savefig(src)
    plt.close(figure)

    out = tmp_path / "out.pdf"
    runner.invoke(app, ["translate", str(src), "--to", "es", "--output", str(out)])
    pending = tmp_path / "out.pdf.pending.json"
    payload = json.loads(pending.read_text(encoding="utf-8"))

    sources = [block["source"] for block in payload["blocks"]]
    assert sources.count("Total") == 1, "an identical block was asked for twice"

    for block in payload["blocks"]:
        block["translation"] = "Suma"
    pending.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    result = runner.invoke(app, ["translate", str(src), "--to", "es", "--output", str(out)])
    assert result.exit_code == 0, result.output

    from docs.infrastructure.pdf.pypdfium2_text_edit_adapter import Pypdfium2TextEditAdapter

    texts = [run.text for run in Pypdfium2TextEditAdapter().read_runs(out)]
    assert texts.count("Suma") == 2, "both occurrences must carry the translation"


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("notapdf.pdf", b"esto no es un pdf en absoluto"),
        ("truncated.pdf", b"%PDF-1.7\nstartxref\n999999\n%%EOF\n"),
    ],
)
def test_a_malformed_pdf_exits_non_zero(tmp_path, name, content):
    """`AGENTS.md` promises exit codes usable in CI. A malformed input
    reported as a successful translation would make that promise false."""
    src = tmp_path / name
    src.write_bytes(content)
    result = runner.invoke(app, ["translate", str(src), "--to", "es"])
    assert result.exit_code != 0


def test_a_pdf_with_no_text_layer_exits_non_zero(tmp_path):
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("pdf")
    import matplotlib.pyplot as plt

    figure = plt.figure(figsize=(4, 3))
    src = tmp_path / "blank.pdf"
    figure.savefig(src)
    plt.close(figure)
    result = runner.invoke(app, ["translate", str(src), "--to", "es"])
    assert result.exit_code != 0
    assert "capa de texto" in result.output
