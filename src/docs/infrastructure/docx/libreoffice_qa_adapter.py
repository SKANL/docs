# src/docs/infrastructure/docx/libreoffice_qa_adapter.py
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def resolve_libreoffice_executable(paths: dict[str, Any]) -> str | None:
    resolved = shutil.which("soffice") or shutil.which("libreoffice")
    if resolved:
        return resolved
    configured = paths.get("libreoffice_bin")
    if configured and Path(configured).exists() and Path(configured).is_file():
        return str(configured)
    for candidate in paths.get("libreoffice_fallbacks", []):
        candidate_path = Path(candidate)
        if candidate_path.exists() and candidate_path.is_file():
            return str(candidate_path)
    return None


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
            proc = subprocess.run(
                [sys.executable, str(script_path), str(docx_path.resolve())],
                cwd=output_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
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
