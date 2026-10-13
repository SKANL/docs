// Typed client for the specialist tools (S6.2 contract): collection, rules, DOCX, translation, diagnostics, issue codes, import.
import { defined, docPath, jsonInit, type Transport } from "../http";
import type { TemplateIssue } from "./templates";

export type FileTool = "collect-sources" | "collect-issues" | "collect-code-evidence" | "build-rules" | "build-ledger";
const FILE_TOOL_PATH: Record<FileTool, string> = {
  "collect-sources": "collect-sources", "collect-issues": "collect-issues", "collect-code-evidence": "collect-code-evidence", "build-rules": "build-rules", "build-ledger": "build-ledger",
};

/** A tool that writes one workspace file. `degraded` means it could not run and `message` says why. */
export interface ToolFileResult { document_id: string; path: string | null; degraded?: boolean; message?: string | null }
export interface RulesReview { document_id: string; strict: boolean; passed: boolean; issues: TemplateIssue[] }
export interface DocxBuilt { document_id: string; built: boolean; docx: string | null; message?: string | null }
export interface FormatAudit { document_id: string; docx: string; strict: boolean; passed: boolean; issues: TemplateIssue[]; report: string }

export interface TranslateInput { artifactId?: string; filename?: string; contentBase64?: string; to: string; sourceLang?: string; output?: string; overwrite?: boolean }
export interface TranslateResult {
  status: "translated" | "unavailable" | "untranslatable"; source?: string | null; output?: string | null; pending?: string | null;
  report?: Record<string, unknown> | null; line?: string | null; message?: string | null;
}

export type DiagnosticStatus = "ok" | "warn" | "error" | "unavailable";
export interface DiagnosticCheck { name: string; status: DiagnosticStatus; required: boolean; detail: string; version?: string | null }
export interface Diagnostics {
  document_id: string; passed: boolean; strict: boolean; checks: DiagnosticCheck[];
  capabilities: Record<string, unknown>; capability_diagnostics: Record<string, unknown>;
}
export interface IssueCodeExplained { code: string; family: string; family_description: string; meaning: string; fix: string }
export interface DocumentSummary { document_id: string; summary: Record<string, unknown> }
export interface SourceImported { document_id: string; filename: string; path: string; sha256: string; size: number; mime_type: string; deduplicated: boolean }

export interface ToolsApi {
  getDiagnostics(input?: { documentId?: string; strict?: boolean }): Promise<Diagnostics>;
  explainIssueCode(code: string): Promise<IssueCodeExplained>;
  runFileTool(tool: FileTool, documentId: string, options?: { repoRoot?: string }): Promise<ToolFileResult>;
  reviewRules(documentId: string, input?: { strict?: boolean }): Promise<RulesReview>;
  buildDocx(documentId: string, input?: { output?: string }): Promise<DocxBuilt>;
  auditDocxFormat(documentId: string, input?: { strict?: boolean; artifactId?: string }): Promise<FormatAudit>;
  translatePdf(input: TranslateInput): Promise<TranslateResult>;
  getDocumentSummary(documentId: string): Promise<DocumentSummary>;
  downloadTranslation(path: string): Promise<Blob>;
  importSourceFile(documentId: string, input: { filename: string; content_base64: string }): Promise<SourceImported>;
}

export function createToolsApi(t: Transport): ToolsApi {
  const request = t.scoped;
  return {
    getDiagnostics: ({ documentId, strict } = {}) => {
      const query = new URLSearchParams();
      if (documentId) query.set("document_id", documentId);
      if (strict) query.set("strict", "true");
      return request(`diagnostics${query.size ? `?${query}` : ""}`);
    },
    explainIssueCode: code => request(`issue-codes/${encodeURIComponent(code)}`),
    runFileTool: (tool, id, { repoRoot } = {}) => request(`${docPath(id)}/${FILE_TOOL_PATH[tool]}`, jsonInit("POST", defined({ repo_root: repoRoot }))),
    reviewRules: (id, { strict } = {}) => request(`${docPath(id)}/review-rules`, jsonInit("POST", defined({ strict }))),
    buildDocx: (id, { output } = {}) => request(`${docPath(id)}/build-docx`, jsonInit("POST", defined({ output }))),
    auditDocxFormat: (id, { strict, artifactId } = {}) => request(`${docPath(id)}/format-audit-docx`, jsonInit("POST", defined({ strict, artifact_id: artifactId }))),
    translatePdf: ({ artifactId, filename, contentBase64, to, sourceLang, output, overwrite }) =>
      request("translations", jsonInit("POST", defined({ artifact_id: artifactId, filename, content_base64: contentBase64, to, source_lang: sourceLang, output, overwrite }))),
    async downloadTranslation(path) {
      const workspaceId = await t.workspaceId();
      return t.send(`translations/output?${new URLSearchParams({ path, workspace_id: workspaceId })}`, { headers: { Accept: "application/pdf" } }, response => response.blob());
    },
    getDocumentSummary: id => request(`${docPath(id)}/summary`),
    importSourceFile: (id, input) => request(`${docPath(id)}/imports`, jsonInit("POST", input)),
  };
}
