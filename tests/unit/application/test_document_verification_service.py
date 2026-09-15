
from typing import ClassVar

from docs.application.document_verification import DocumentVerificationService
from docs.domain.review import Issue


class _Rules:
    issues: ClassVar = [Issue("warning", "rules")]


class _Review:
    def review_document(self, *args, **kwargs):
        return type("Result", (), {"issues": [Issue("error", "document")]})()


class _Evidence:
    def file_exists(self, path):
        return True

    def file_size(self, path):
        return 7


class _Format:
    def audit_format(self, path, config, strict=False):
        return type("Result", (), {"issues": [Issue("warning", "format")]})()


class _Qa:
    def qa_docx(self, config, path, strict=False):
        return path.parent / "qa"


def test_verify_all_preserves_findings_order_and_docx_checks(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "docs.application.document_verification.review_rules",
        lambda *args, **kwargs: _Rules(),
    )
    monkeypatch.setattr(
        "docs.application.document_verification.resolve_normative_settings",
        lambda config: object(),
    )
    docx = tmp_path / "draft.docx"
    docx.write_bytes(b"docx")
    service = DocumentVerificationService(_Review(), _Evidence(), _Format(), _Qa())

    result = service.verify_all("doc", object(), {"paths": {"rules_manifest": "rules"}}, docx_path=docx, strict=True)

    assert [(issue.severity, issue.message) for issue in result.issues] == [
        ("warning", "rules"), ("error", "document"), ("warning", "format"),
        ("warning", "QA visual omitido: LibreOffice no está disponible (auditoría de formato sí se ejecutó)."),
    ]
