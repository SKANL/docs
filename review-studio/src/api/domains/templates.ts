// Typed client for template administration: catalogue, show, install a built-in, create, validate (S6.1 contract).
import type { ScopedRequest } from "./authoring";

export interface CatalogEntry { name: string; installed: boolean }
export interface TemplateShown { name: string; template: Record<string, unknown> }
export interface TemplateWritten { name: string; path: string }
/** One validation finding; the server's issue dictionaries vary, so only code/message/severity are read. */
export interface TemplateIssue { code?: string; severity?: string; message?: string; [key: string]: unknown }
export interface TemplateValidation { name: string; passed: boolean; issues: TemplateIssue[] }

export interface TemplatesApi {
  listTemplateCatalog(): Promise<CatalogEntry[]>;
  showTemplate(name: string): Promise<TemplateShown>;
  installBuiltinTemplate(name: string, options?: { force?: boolean }): Promise<TemplateWritten>;
  createTemplate(name: string): Promise<TemplateWritten>;
  /** `draft` is checked instead of the stored file and is never written. */
  validateTemplate(name: string, draft?: Record<string, unknown>): Promise<TemplateValidation>;
}

const post = (body: Record<string, unknown>): RequestInit => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export function createTemplatesApi(request: ScopedRequest): TemplatesApi {
  const one = (name: string) => `templates/${encodeURIComponent(name)}`;
  return {
    async listTemplateCatalog() { return (await request<{ items?: CatalogEntry[] }>("template-catalog")).items ?? []; },
    showTemplate: name => request(one(name)),
    installBuiltinTemplate: (name, { force = false } = {}) => request(`${one(name)}/use`, post({ force })),
    createTemplate: name => request("templates", post({ name })),
    validateTemplate: (name, draft) => request(`${one(name)}/validate`, post(draft ? { template: draft } : {})),
  };
}
