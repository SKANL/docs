from __future__ import annotations

import zipfile
from contextlib import nullcontext
from pathlib import Path

from docs.application.package_service_v2 import PackageFileV2, PackageServiceV2


def test_package_service_writes_sorted_deterministic_archive_and_replaces_existing_output(
    tmp_path: Path,
) -> None:
    output = tmp_path / "release.zip"
    output.write_bytes(b"previous package")

    PackageServiceV2(lock=lambda _path: nullcontext(), directory_guard=lambda _path: nullcontext()).write(
        output,
        (
            PackageFileV2("z-report.pdf", b"pdf"),
            PackageFileV2("a-report.html", b"html"),
        ),
    )

    with zipfile.ZipFile(output) as archive:
        assert archive.namelist() == ["a-report.html", "z-report.pdf"]
        assert archive.read("a-report.html") == b"html"
        assert archive.read("z-report.pdf") == b"pdf"
        assert all(member.date_time == (1980, 1, 1, 0, 0, 0) for member in archive.infolist())
    assert not list(tmp_path.glob(".release.zip.*.tmp"))


def test_package_service_does_not_import_infrastructure() -> None:
    import ast

    import docs.application.package_service_v2 as package_service

    module = ast.parse(Path(package_service.__file__).read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(module)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert not any(name.startswith("docs.infrastructure") for name in imported_modules)
