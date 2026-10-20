// @vitest-environment jsdom
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { deliveryApi, published } from "./deliveryHarness";
import { openAt, toolsApi } from "./toolsHarness";
import { openPipeline } from "./pipelineHarness";

beforeEach(() => { localStorage.setItem("review-studio.advanced", "true"); });
afterEach(() => { cleanup(); window.location.hash = ""; localStorage.clear(); });

type Copy = { locale: "en" | "es"; deliver: string; destination: string; policy: string; review: string; confirm: string; labels: Record<"draft" | "strict" | "release", string> };
const copies: Copy[] = [
  { locale: "en", deliver: "Deliver", destination: "Destination", policy: "Policy", review: "Review publish", confirm: "Confirm and publish", labels: { draft: "draft", strict: "strict", release: "release" } },
  { locale: "es", deliver: "Entregar", destination: "Destino", policy: "Política", review: "Revisar publicación", confirm: "Confirmar y publicar", labels: { draft: "borrador", strict: "estricta", release: "versión final" } },
];

describe.each(copies)("publish dialog policy labels ($locale)", copy => {
  const openDialog = async (publishDocument: ReturnType<typeof vi.fn>) => {
    localStorage.setItem("review-studio.locale", copy.locale);
    openPipeline("/delivery", deliveryApi({ publishDocument }).api);
    await userEvent.click(await screen.findByRole("button", { name: copy.deliver }));
    const dialog = await screen.findByRole("dialog", { name: copy.deliver });
    await userEvent.type(within(dialog).getByRole("textbox", { name: copy.destination }), "a.html");
    return dialog;
  };

  it("lists translated options, and sends the raw policy value for the chosen one", async () => {
    const publishDocument = vi.fn(async () => published);
    const dialog = await openDialog(publishDocument);
    await userEvent.click(within(dialog).getByRole("combobox", { name: copy.policy }));
    expect((await screen.findAllByRole("option")).map(option => option.textContent)).toEqual([copy.labels.draft, copy.labels.strict, copy.labels.release]);
    await userEvent.click(screen.getByRole("option", { name: copy.labels.strict }));
    await userEvent.click(within(dialog).getByRole("button", { name: copy.review }));
    expect(dialog.textContent).toContain(copy.labels.strict);
    await userEvent.click(within(dialog).getByRole("button", { name: copy.confirm }));
    await waitFor(() => expect(publishDocument).toHaveBeenCalledWith("doc-1", { destination: "a.html", policy: "strict" }));
  });

  it("shows the translated default and still sends \"release\"", async () => {
    const publishDocument = vi.fn(async () => published);
    const dialog = await openDialog(publishDocument);
    expect(within(dialog).getByRole("combobox", { name: copy.policy }).textContent).toBe(copy.labels.release);
    await userEvent.click(within(dialog).getByRole("button", { name: copy.review }));
    await userEvent.click(within(dialog).getByRole("button", { name: copy.confirm }));
    await waitFor(() => expect(publishDocument).toHaveBeenCalledWith("doc-1", { destination: "a.html", policy: "release" }));
  });
});

describe("diagnostics status badge", () => {
  const checks = [
    { name: "fonts", status: "warn", required: false, detail: "substituted", version: null },
    { name: "weird", status: "degraded-ish", required: false, detail: "new server word", version: null },
  ];
  const getDiagnostics = async () => ({ document_id: "doc-1", passed: false, strict: false, capabilities: {}, capability_diagnostics: {}, checks });
  const statusCell = (table: HTMLElement, name: string) => within(table).getByText(name).closest("tr")!.querySelectorAll("td")[1].textContent;

  it.each([["en", "Diagnostic checks", "warning"], ["es", "Comprobaciones de diagnóstico", "aviso"]])("translates a known status in %s and shows an unknown one raw", async (locale, tableName, word) => {
    localStorage.setItem("review-studio.locale", locale);
    openAt("/configure/diagnostics", toolsApi({ getDiagnostics }));
    const table = await screen.findByRole("table", { name: tableName });
    expect(statusCell(table, "fonts")).toBe(word);
    expect(statusCell(table, "weird")).toBe("degraded-ish");
  });
});

describe("release panel in Spanish", () => {
  // Root cause of the "never saw the Release button" report: the panel is gated behind the Avanzado switch, and the Spanish check never looked for it.
  it("stays hidden until the Avanzado switch is on", async () => {
    localStorage.setItem("review-studio.locale", "es");
    localStorage.removeItem("review-studio.advanced");
    openPipeline("/delivery", deliveryApi().api);
    await screen.findByRole("button", { name: "Empaquetar" });
    expect(screen.queryByRole("region", { name: "Versión final" })).toBeNull();
  });

  it("shows the translated release panel and starts a release run", async () => {
    localStorage.setItem("review-studio.locale", "es");
    const runDocument = vi.fn(async () => ({ id: "run-rel", status: "queued", document_id: "doc-1", pipeline_id: "document", format: "html", policy: "release", links: { self: "", progress: "", cancel: "" } }));
    openPipeline("/delivery", deliveryApi({ runDocument }).api);
    const panel = await screen.findByRole("region", { name: "Versión final" });
    expect(panel.textContent).toContain("Inicia una generación con la política de versión final para doc-1");
    expect(screen.queryByText("Start release run")).toBeNull();
    await userEvent.click(within(panel).getByRole("button", { name: "Iniciar generación de versión final" }));
    await waitFor(() => expect(runDocument).toHaveBeenCalledWith("doc-1", { policy: "release" }));
  });
});
