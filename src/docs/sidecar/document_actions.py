"""Document operations the API delegates to the CLI's application composition."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from docs.application.pipeline_service import PipelineRequest
from docs.application.workspaces import WorkspaceRegistry
from docs.composition import ApplicationComposition, compose_application
from docs.domain.authoring_clock import authoring_timestamp
from docs.domain.normative import resolve_normative_settings
from docs.domain.workspace import Workspace


def workspace_services(workspace_root: str | Path) -> ApplicationComposition:
    """The composed application the CLI uses, for one workspace root."""
    root = Path(workspace_root)
    return compose_application(Workspace(root / "documents", root / "templates"))


class DocumentActions:
    """Prepare, build, verify, revise and read context of documents for the API."""

    def __init__(self, registry: WorkspaceRegistry) -> None:
        self._registry = registry

    def document_service(self, workspace_root: str) -> Any:
        return workspace_services(workspace_root).documents

    def run_action(self, workspace_root: str, document_id: str, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        deps = workspace_services(workspace_root)
        if action == "prepare" and not (deps.workspace.doc_root(document_id) / "document.json").is_file():
            self._create_from_import_metadata(deps, document_id)
        resolved = deps.resolve_context(document_id)
        if action == "prepare":
            return self._prepare(deps, document_id, resolved)
        pipeline_id = "document" if action == "build" else "document-verify"
        run_id = str(payload.get("run_id") or f"api-{action}-{uuid4().hex}")
        service = deps.create_document_pipeline_service(
            output_format=str(payload.get("format", "docx")),
            document=document_id,
            pipeline_id=pipeline_id,
            provenance_run_id=run_id,
        )
        report = service.execute(PipelineRequest(run_id=run_id, publish=action == "build", pipeline_id=pipeline_id))
        return report.to_dict()

    @staticmethod
    def _create_from_import_metadata(deps: ApplicationComposition, document_id: str) -> None:
        metadata_files = sorted((deps.workspace.doc_root(document_id) / "inbox").glob("*.import.json"))
        if metadata_files:
            metadata = json.loads(metadata_files[0].read_text(encoding="utf-8"))
            deps.documents.create(
                document_id,
                str(metadata.get("template", "documento-generico")),
                str(metadata.get("title", document_id)),
            )

    @staticmethod
    def _prepare(deps: ApplicationComposition, document_id: str, resolved: Any) -> dict[str, Any]:
        pipeline = deps.create_source_pipeline()
        report = pipeline.prepare(document_id, deps.workspace.doc_root(document_id), resolved.config)
        if report.get("succeeded"):
            report["scaffolds"] = [
                str(deps.section.build_section(document_id, resolved.template, section.id, resolved.config))
                for section in resolved.template.sections
            ]
        return report

    def context(self, workspace_root: str, document_id: str) -> dict[str, Any]:
        deps = workspace_services(workspace_root)
        resolved = deps.resolve_context(document_id)
        statuses = deps.context.status(document_id, resolved.template)
        return {
            "document_id": document_id,
            "topics": [
                {
                    "id": item.id,
                    "title": item.title,
                    "required": item.required,
                    "exists": item.exists,
                    "missing": item.missing,
                    "fields": [
                        {"key": field.key, "label": field.label, "required": field.required}
                        for field in next(
                            (topic.fields for topic in resolved.template.context_schema.topics if topic.id == item.id),
                            (),
                        )
                    ],
                }
                for item in statuses
            ],
        }

    def read_context(self, document_id: str, workspace_root: str | None = None) -> dict[str, Any]:
        root = workspace_root if workspace_root is not None else str(self._active_root())
        return self.context(root, document_id)

    def set_context(
        self, document_id: str, topic: str, field: str, value: str, workspace_root: str | None = None
    ) -> dict[str, Any]:
        root = Path(workspace_root) if workspace_root else self._active_root()
        deps = workspace_services(root)
        resolved = deps.resolve_context(document_id)
        path = deps.context.set(document_id, resolved.template, topic, value, field)
        return {"document_id": document_id, "topic": topic, "field": field, "path": str(path)}

    def revise(self, document_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        deps = workspace_services(self._active_root())
        resolved = deps.resolve_context(document_id)
        target_id = str(payload.get("target_id") or payload.get("section_id") or payload.get("topic_id") or "")
        request = str(payload.get("request") or "API revision")
        value = payload.get("new_body", payload.get("new_value", payload.get("value")))
        if not target_id or not isinstance(value, str):
            raise ValueError("target_id and string new_body/new_value are required")
        config_values = resolved.config
        strict = bool(payload.get("strict", False))
        normative = resolve_normative_settings(config_values)
        manifest_exists, manifest_size = deps.rules_manifest_state(config_values)
        now = authoring_timestamp()
        if deps.revision.resolve_target(resolved.template, target_id) == "topic":
            result = deps.revision.revise_topic(
                document_id,
                resolved.template,
                config_values,
                topic_id=target_id,
                request=request,
                strict=strict,
                manifest_exists=manifest_exists,
                manifest_size=manifest_size,
                normative=normative,
                now=now,
                new_value=value,
                field=str(payload.get("field", "")),
            )
        else:
            result = deps.revision.revise(
                document_id,
                resolved.template,
                config_values,
                section_id=target_id,
                new_body=value,
                request=request,
                strict=strict,
                manifest_exists=manifest_exists,
                manifest_size=manifest_size,
                normative=normative,
                now=now,
            )
        return result.to_dict()

    def _active_root(self) -> Path:
        active = self._registry.active()
        if active is None:
            raise RuntimeError("workspace_not_configured")
        return Path(str(active["root"]))
