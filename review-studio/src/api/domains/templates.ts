// Typed client for template administration (catalogue, show, install a built-in, create, validate; S6.1 contract) and the plugin registry.
import { jsonInit, listPage, type ListParams, type Transport } from "../http";
import type { Status } from "./review";

export type Template = { id: string; name: string; version: string; sections: number; contract: Status; updated: string };

export interface CatalogEntry { name: string; installed: boolean }
export interface TemplateShown { name: string; template: Record<string, unknown> }
export interface TemplateWritten { name: string; path: string }
/** One validation finding; the server's issue dictionaries vary, so only code/message/severity are read. */
export interface TemplateIssue { code?: string; severity?: string; message?: string; [key: string]: unknown }
export interface TemplateValidation { name: string; passed: boolean; issues: TemplateIssue[] }

export interface TemplatesApi {
  listTemplates(params?: ListParams): Promise<Template[]>;
  listPlugins(params?: ListParams): Promise<Record<string, unknown>[]>;
  getPlugin(id: string): Promise<Record<string, unknown>>;
  listTemplateCatalog(): Promise<CatalogEntry[]>;
  showTemplate(name: string): Promise<TemplateShown>;
  installBuiltinTemplate(name: string, options?: { force?: boolean }): Promise<TemplateWritten>;
  createTemplate(name: string): Promise<TemplateWritten>;
  /** `draft` is checked instead of the stored file and is never written. */
  validateTemplate(name: string, draft?: Record<string, unknown>): Promise<TemplateValidation>;
}

export function createTemplatesApi(t: Transport): TemplatesApi {
  const request = t.scoped;
  const one = (name: string) => `templates/${encodeURIComponent(name)}`;
  return {
    listTemplates: async params => (await listPage<Template>(request, "templates", params)).items,
    listPlugins: async params => (await listPage<Record<string, unknown>>(request, "plugins", params)).items,
    getPlugin: id => request(`plugins/${encodeURIComponent(id)}`),
    async listTemplateCatalog() { return (await request<{ items?: CatalogEntry[] }>("template-catalog")).items ?? []; },
    showTemplate: name => request(one(name)),
    installBuiltinTemplate: (name, { force = false } = {}) => request(`${one(name)}/use`, jsonInit("POST", { force })),
    createTemplate: name => request("templates", jsonInit("POST", { name })),
    validateTemplate: (name, draft) => request(`${one(name)}/validate`, jsonInit("POST", draft ? { template: draft } : {})),
  };
}
