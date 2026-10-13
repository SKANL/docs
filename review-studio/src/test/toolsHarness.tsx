import { render } from "@testing-library/react";
import App from "../App";
import type { Capability, ReviewApi } from "../api/models";
import { makeApi } from "./authoringHarness";

const cap = (id: string, status: Capability["status"] = "available"): Capability => ({
  id, cli_command: id.replace(".", " "), route: status === "available" ? "POST /v2/x" : null, scopes: [], surface: "web+desktop", slice: "S6", status,
});
export const toolCapabilityIds = [
  "template.list", "template.show", "template.use", "template.create", "template.init", "template.validate", "doctor", "explain",
  "collect-sources", "collect-issues", "collect-code-evidence", "build-rules", "build-ledger", "review-rules", "build-docx", "format-audit-docx", "translate",
  "doc.show", "doc.status", "document.import", "source.ingest", "plugins.list", "plugins.show",
];
export const toolsCatalog = (...missing: string[]) => ({ groups: [{ id: "tools", capabilities: toolCapabilityIds.map(id => cap(id, missing.includes(id) ? "planned" : "available")) }] });

export const ok = (path: string) => ({ document_id: "doc-1", path });
/** Overrides are loosely typed on purpose: tests feed the UI server-shaped data, including malformed data. */
export function toolsApi(overrides: Record<string, unknown> = {}): ReviewApi {
  return makeApi({
    getCapabilities: async () => toolsCatalog(),
    listTemplates: async () => [{ id: "report", name: "report", version: "1", sections: 2, contract: "passed", updated: "2026-01-01" }],
    listTemplateCatalog: async () => [{ name: "report", installed: true }, { name: "memo", installed: false }],
    showTemplate: async (name: string) => ({ name, template: { title: "Report", sections: [{ id: "intro", title: "Intro" }] } }),
    installBuiltinTemplate: async (name: string) => ({ name, path: `templates/${name}.json` }),
    createTemplate: async (name: string) => ({ name, path: `templates/${name}.json` }),
    validateTemplate: async (name: string) => ({ name, passed: true, issues: [] }),
    listPlugins: async () => [{ id: "pdf-helper", version: "1.0", capabilities: ["translate"], trust: "unsigned" }],
    getPlugin: async (id: string) => ({ id, version: "1.0", capabilities: ["translate"], trust: "unsigned", digest: "abc" }),
    getDiagnostics: async () => ({ document_id: "doc-1", passed: true, strict: false, checks: [{ name: "pandoc", status: "ok", required: true, detail: "pandoc (3.1)", version: "3.1" }], capabilities: {}, capability_diagnostics: {} }),
    explainIssueCode: async (code: string) => ({ code, family: "QA", family_description: "Quality gates", meaning: "A thing is wrong", fix: "Fix the thing" }),
    runFileTool: async () => ok("artifacts/out.json"),
    reviewRules: async () => ({ document_id: "doc-1", strict: false, passed: true, issues: [] }),
    buildDocx: async () => ({ document_id: "doc-1", built: true, docx: "documents/doc-1/draft/doc-1.docx" }),
    auditDocxFormat: async () => ({ document_id: "doc-1", docx: "d.docx", strict: false, passed: true, issues: [], report: "# Format audit\n\nAll good" }),
    translatePdf: async () => ({ status: "translated", source: "a.pdf", output: "artifacts/translations/a.es.pdf", pending: null, report: { blocks_total: 4, blocks_translated: 4 }, line: "4/4 blocks" }),
    listArtifacts: async () => [{ id: "art-1", name: "manual.pdf", runId: "run-1", kind: "PDF", size: "1 KB", status: "passed", checksum: "x" }],
    getDocument: async (id: string) => ({ id, title: "Field notes", template: "report", lifecycle: "draft" }),
    getDocumentSummary: async (id: string) => ({ document_id: id, summary: { stage: "assembled", sections: 2, next: "build" } }),
    importSourceFile: async (id: string, input: { filename: string }) => ({ document_id: id, filename: input.filename, path: `documents/${id}/imports/${input.filename}`, sha256: "f".repeat(64), size: 3, mime_type: "text/markdown", deduplicated: false }),
    ...overrides,
  } as unknown as Partial<ReviewApi>);
}

export function openAt(path: string, api: ReviewApi) {
  window.location.hash = `#${path}`;
  return render(<App api={api} />);
}
