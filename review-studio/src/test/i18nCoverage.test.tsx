// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import App from "../App";
import { ApiError } from "../api/errors";
import { makeApi } from "./authoringHarness";
import { openAt, toolsApi } from "./toolsHarness";
import { deliveryApi } from "./deliveryHarness";
import { openPipeline, streamingApi } from "./pipelineHarness";
import type { ReviewApi } from "../api/models";
import { en, es } from "../lib/i18n/messages";

afterEach(() => { cleanup(); window.location.hash = ""; localStorage.clear(); });

const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map(match => match[1]).sort();

describe("dictionary guards", () => {
  it("Spanish has exactly the English keys, all non-empty", () => {
    expect(Object.keys(es).sort()).toEqual(Object.keys(en).sort());
    expect(Object.entries(es).filter(([, text]) => !text.trim())).toEqual([]);
  });
  it("each key uses the same {placeholders} in both languages", () => {
    const mismatched = Object.keys(en).filter(key => placeholders(en[key as keyof typeof en]).join() !== placeholders(es[key as keyof typeof es]).join());
    expect(mismatched).toEqual([]);
  });
});

const workspace = { id: "ws-1", name: "Research", root: "C:/data" };
const area = (over: Record<string, unknown> = {}) => ({
  listFindings: async () => [], listArtifacts: async () => [], listTemplates: async () => [], listBaselines: async () => [], listRevisions: async () => [],
  listWorkspaces: async () => [workspace], listDocuments: async () => [], getCurrentDocument: async () => ({ current_document_id: null, document: null }),
  createWorkspace: async () => { throw new ApiError("UNIQUE constraint failed: workspaces.name", 409, "exists", undefined, "rq-9"); },
  ...over,
}) as unknown as ReviewApi;

describe("language switch", () => {
  it("renders the workspace screen in Spanish, then in English after the switch", async () => {
    localStorage.setItem("review-studio.locale", "es");
    window.location.hash = "#/configure/workspaces";
    localStorage.setItem("review-studio.advanced", "true");
    render(<App api={area()} />);
    expect(await screen.findByRole("heading", { name: "Espacio de trabajo y documentos" }, { timeout: 5000 })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Workspace and document control" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Idioma" }));
    expect(await screen.findByRole("heading", { name: "Workspace and document control" })).toBeTruthy();
  });

  it("shows dialog failures as plain language with the raw text under Technical details", async () => {
    window.location.hash = "#/configure/workspaces";
    localStorage.setItem("review-studio.advanced", "true");
    render(<App api={area()} />);
    fireEvent.click(await screen.findByRole("button", { name: "Create workspace" }, { timeout: 5000 }));
    const dialog = await screen.findByRole("dialog", { name: "Create workspace" });
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Workspace name" }), { target: { value: "Studio" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Create workspace" }));
    const alert = await within(dialog).findByRole("alert");
    expect(alert.textContent).toContain(en["error.conflict"]);
    expect(alert.querySelector("details")!.textContent).toContain("UNIQUE constraint failed");
  });
});

describe("authoring screen", () => {
  it("renders tabs, sources and sections in Spanish", async () => {
    localStorage.setItem("review-studio.locale", "es");
    localStorage.setItem("review-studio.mode", "write");
    window.location.hash = "#/authoring/sources";
    render(<App api={makeApi({ ingestSources: async () => ({}) } as never)} />);
    expect(await screen.findByLabelText("Archivos de fuentes", {}, { timeout: 5000 })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Clasificación" })).toBeTruthy();
    await userEvent.click(screen.getByRole("tab", { name: "Secciones" }));
    expect(await screen.findByRole("button", { name: "Guardar sección" })).toBeTruthy();
    expect(screen.getByLabelText("Contenido de la sección")).toBeTruthy();
    expect(screen.queryByText("Section body")).toBeNull();
  });
});

describe("pipeline screen", () => {
  it("renders launcher and history in Spanish, with the status words translated", async () => {
    localStorage.setItem("review-studio.locale", "es");
    openPipeline("/pipeline", streamingApi().api);
    expect(await screen.findByRole("combobox", { name: "Formato de salida" }, { timeout: 5000 })).toBeTruthy();
    expect(screen.getByRole("combobox", { name: "Política" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Generaciones" })).toBeTruthy();
    expect(await screen.findByText("en curso")).toBeTruthy();
    expect(screen.queryByText("Run pipeline")).toBeNull();
  }, 20_000);
});

describe("review screen", () => {
  it("renders findings and their severity words in Spanish", async () => {
    localStorage.setItem("review-studio.locale", "es");
    window.location.hash = "#/review/findings";
    const finding = { id: "f-1", severity: "high", message: "Missing citation", run_id: "r1", section: "intro", page: 3 };
    render(<App api={area({ listFindings: async () => [finding], getCapabilities: async () => ({ groups: [{ id: "g", capabilities: [{ id: "findings.list", cli_command: null, route: "GET /v2/findings", scopes: [], surface: "web+desktop", slice: "S4", status: "available" }] }] }) })} />);
    expect(await screen.findByLabelText("Filtrar hallazgos", {}, { timeout: 5000 })).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: "Gravedad" })).toBeTruthy();
    expect(screen.getByText("alta")).toBeTruthy();
    expect(screen.getByText("sección intro · página 3")).toBeTruthy();
    expect(screen.queryByText("section intro · page 3")).toBeNull();
  }, 20_000);
});

describe("delivery screen", () => {
  it("renders the delivery area in Spanish", async () => {
    localStorage.setItem("review-studio.locale", "es");
    localStorage.setItem("review-studio.advanced", "true");
    openPipeline("/delivery", deliveryApi().api);
    expect(await screen.findByRole("heading", { name: "Entrega" }, { timeout: 5000 })).toBeTruthy();
    expect(await screen.findByRole("heading", { name: "Historial de publicaciones" })).toBeTruthy();
    expect(await screen.findByRole("button", { name: "Empaquetar" })).toBeTruthy();
    expect(screen.queryByText("Package")).toBeNull();
  }, 20_000);
});

describe("configure screens", () => {
  it("renders templates and diagnostics in Spanish", async () => {
    localStorage.setItem("review-studio.locale", "es");
    openAt("/configure/templates", toolsApi());
    expect(await screen.findByRole("table", { name: "Plantillas instaladas" }, { timeout: 5000 })).toBeTruthy();
    expect(screen.getByRole("table", { name: "Catálogo integrado" })).toBeTruthy();
    expect(screen.getByRole("navigation", { name: "Secciones de configuración" })).toBeTruthy();
    expect(screen.queryByText("Installed templates")).toBeNull();
    cleanup();
    openAt("/configure/diagnostics", toolsApi());
    expect(await screen.findByRole("table", { name: "Comprobaciones de diagnóstico" }, { timeout: 5000 })).toBeTruthy();
  }, 20_000);
});

describe("tools screen", () => {
  it("renders the specialist tools in Spanish and opens one", async () => {
    localStorage.setItem("review-studio.locale", "es");
    openAt("/tools", toolsApi());
    expect(await screen.findByRole("button", { name: "Abrir Revisar reglas" }, { timeout: 5000 })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Abrir Traducir PDF" })).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Abrir Generar DOCX" }));
    expect(await screen.findByRole("button", { name: "Ejecutar Generar DOCX" })).toBeTruthy();
    expect(screen.queryByText("Build DOCX")).toBeNull();
  }, 20_000);
});
