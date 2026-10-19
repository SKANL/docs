// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import App from "../App";
import type { Capability, ReviewApi } from "../api/models";

const cap = (id: string, slice: string, cli: string | null = id.replace(".", " ")): Capability => ({ id, cli_command: cli, route: "GET /v2/x", scopes: [], surface: "web+desktop", slice, status: "available" });
const api = (...caps: Capability[]) => ({
  listFindings: async () => [], listArtifacts: async () => [], listWorkspaces: async () => [],
  getCapabilities: async () => ({ groups: [{ id: "g", capabilities: caps }] }),
}) as unknown as ReviewApi;
const catalog = [cap("document.build", "S3"), cap("doc.new", "S1"), cap("build-section", "S2"), cap("brand.new.thing", "S3", "brand new thing")];

afterEach(() => { cleanup(); window.location.hash = ""; localStorage.clear(); });
async function openPalette(over: Record<string, string> = {}) {
  localStorage.setItem("review-studio.mode", over.mode ?? "supervise");
  for (const [key, value] of Object.entries(over)) if (key !== "mode") localStorage.setItem(key, value);
  render(<App api={api(...catalog)} />);
  await userEvent.click(screen.getByRole("button", { name: "Open command menu" }));
  const palette = await screen.findByRole("dialog", { name: /command palette/i });
  await within(palette).findByText("Build the document");
  return palette;
}

describe("command palette capabilities", () => {
  it("shows plain-language labels, with the CLI string only as an Advanced hint", async () => {
    const palette = await openPalette();
    expect(within(palette).queryByText("document build")).toBeNull();
    cleanup();
    const advanced = await openPalette({ "review-studio.advanced": "true" });
    expect(within(advanced).getByText("document build")).toBeTruthy();
    expect(within(advanced).getByText("Build the document")).toBeTruthy();
  });

  it("follows the navigation visibility rule: items for hidden areas need Advanced (or Write mode)", async () => {
    const palette = await openPalette();
    expect(within(palette).queryByText("Create a document")).toBeNull();
    expect(within(palette).queryByText("Build a section")).toBeNull();
    cleanup();
    expect(within(await openPalette({ mode: "write" })).getByText("Build a section")).toBeTruthy();
    cleanup();
    expect(within(await openPalette({ "review-studio.advanced": "true" })).getByText("Create a document")).toBeTruthy();
  });

  it("falls back to the CLI string for a capability it has no label for", async () => {
    const palette = await openPalette();
    expect(within(palette).getByText("brand new thing")).toBeTruthy();
  });

  it("labels items in Spanish", async () => {
    localStorage.setItem("review-studio.locale", "es");
    localStorage.setItem("review-studio.mode", "supervise");
    render(<App api={api(...catalog)} />);
    await userEvent.click(screen.getByRole("button", { name: "Abrir menú de comandos" }));
    await waitFor(async () => expect(within(await screen.findByRole("dialog")).getByText("Generar el documento")).toBeTruthy());
  });
});
