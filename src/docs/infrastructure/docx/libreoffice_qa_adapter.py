# src/docs/infrastructure/docx/libreoffice_qa_adapter.py
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from docs.infrastructure.tools.resolution import (
    libreoffice_locations,
    resolve_executable,
)


def resolve_libreoffice_executable(paths: dict[str, Any]) -> str | None:
    """Find LibreOffice, including where its installer actually puts it.

    The Windows installer does NOT add itself to PATH, so a perfectly normal
    install at `%ProgramFiles%\LibreOffice\program\soffice.exe` used to
    resolve to nothing: the harness told a user to install software they
    already had, refused `--format pdf`, and skipped visual QA. It answers to
    `soffice` on Windows and `libreoffice` on most Linux packages, so both
    names are tried.
    """
    return resolve_executable(
        paths,
        names=("soffice", "libreoffice"),
        config_prefix="libreoffice",
        well_known=libreoffice_locations(),
    )


class LibreOfficeQaAdapter:
    def render_docx_to_pdf(self, config: dict[str, Any], docx_path: Path, output_dir: Path) -> Path:
        paths = config.get("paths", {})
        libreoffice = resolve_libreoffice_executable(paths)
        if not libreoffice:
            raise RuntimeError(
                "LibreOffice/soffice no está disponible en PATH. Instálalo para renderizar QA visual."
            )

        expected_pdf = output_dir / f"{docx_path.stem}.pdf"
        if expected_pdf.exists():
            expected_pdf.unlink()
        with tempfile.TemporaryDirectory(prefix="docs_lo_profile_") as profile:
            subprocess.run(
                [
                    libreoffice,
                    f"-env:UserInstallation={Path(profile).resolve().as_uri()}",
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(output_dir),
                    str(docx_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        if not expected_pdf.exists() or expected_pdf.stat().st_size == 0:
            raise RuntimeError(f"LibreOffice no produjo el PDF esperado: {expected_pdf}")
        return expected_pdf

    def run_documents_audits(
        self, config: dict[str, Any], docx_path: Path, output_dir: Path, strict: bool = False
    ) -> list[dict[str, Any]]:
        if not config.get("documents_tools", {}).get("enabled", True):
            return []
        scripts_dir_value = config.get("paths", {}).get("documents_scripts_dir")
        scripts_dir = Path(scripts_dir_value) if scripts_dir_value else None
        safe_scripts = ["heading_audit.py", "section_audit.py", "style_lint.py", "table_geometry.py"]
        results: list[dict[str, Any]] = []
        for script in safe_scripts:
            script_path = scripts_dir / script if scripts_dir else None
            if script_path is None or not script_path.exists():
                results.append({"name": script, "ok": not strict, "stdout": "", "stderr": "script no encontrado"})
                continue
            # check=False on purpose: a failing audit script's stderr is
            # captured into the per-script report below, so a non-zero exit
            # is DATA here, not an exception.
            proc = subprocess.run(
                [sys.executable, str(script_path), str(docx_path.resolve())],
                cwd=output_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            out_path = output_dir / f"documents-{script.removesuffix('.py')}.txt"
            out_path.write_text(
                (proc.stdout or "") + ("\nSTDERR:\n" + proc.stderr if proc.stderr else ""), encoding="utf-8"
            )
            results.append(
                {
                    "name": script,
                    "ok": proc.returncode == 0,
                    "stdout": proc.stdout[-2000:] if proc.stdout else "",
                    "stderr": proc.stderr[-2000:] if proc.stderr else "",
                    "report": out_path.resolve().as_posix(),
                }
            )
        return results
