// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import App from "../App";
import css from "../app/styles/globals.css?inline";
import type { CapabilityCatalog, ReviewApi } from "../api/models";

const catalog: CapabilityCatalog = { groups: [{ id: "workspace", capabilities: [
  { id: "workspace.list", cli_command: "workspace list", route: "GET /v2/workspaces", scopes: [], surface: "web+desktop", slice: "S1", status: "available" },
  { id: "stamp", cli_command: "stamp", route: null, scopes: [], surface: "web+desktop", slice: "S0", status: "planned" },
] }] };

function makeApi(overrides: Partial<ReviewApi> = {}): ReviewApi {
  return {
    listRuns: async () => [], listFindings: async () => [], listArtifacts: async () => [],
    listWorkspaces: async () => [], getCapabilities: async () => catalog,
    getGraph: async () => ({ nodes: [], edges: [] }), getGraphQuery: async () => ({ items: [], graphUnavailable: false }),
    ...overrides,
  } as unknown as ReviewApi;
}

afterEach(() => { cleanup(); window.location.hash = ""; });

describe("application shell", () => {
  it("moves focus to the main region when the route changes", async () => {
    window.location.hash = "#/";
    render(<App api={makeApi()} />);
    await userEvent.click(within(screen.getByRole("navigation", { name: "Task areas" })).getByRole("link", { name: "Pipeline" }));
    await waitFor(() => expect(document.activeElement?.id).toBe("main"));
    expect(screen.getByRole("heading", { name: "Pipeline" })).toBeTruthy();
  });

  it("offers a skip link that targets and focuses the main region", async () => {
    render(<App api={makeApi()} />);
    const skip = screen.getByRole("link", { name: "Skip to content" });
    expect(skip.getAttribute("href")).toBe("#main");
    expect(document.getElementById("main")).toBeTruthy();
    await userEvent.click(skip);
    expect(document.activeElement?.id).toBe("main");
    expect(window.location.hash).not.toBe("#main");
  });

  it("opens the command palette with Ctrl+K, closes it with Escape and restores focus", async () => {
    render(<App api={makeApi()} />);
    const trigger = screen.getByRole("button", { name: "Open command menu" });
    trigger.focus();
    await userEvent.keyboard("{Control>}k{/Control}");
    expect(await screen.findByRole("dialog", { name: /command palette/i })).toBeTruthy();
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog", { name: /command palette/i })).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(trigger));
  });

  it("lists navigation plus only enabled capabilities as palette actions", async () => {
    render(<App api={makeApi()} />);
    await userEvent.click(screen.getByRole("button", { name: "Open command menu" }));
    const palette = await screen.findByRole("dialog", { name: /command palette/i });
    expect(within(palette).getByText("Authoring")).toBeTruthy();
    await waitFor(() => expect(within(palette).getByText("workspace list")).toBeTruthy());
    expect(within(palette).queryByText("stamp")).toBeNull();
  });

  it("navigates from a palette item", async () => {
    render(<App api={makeApi()} />);
    await userEvent.click(screen.getByRole("button", { name: "Open command menu" }));
    await userEvent.click(await screen.findByRole("option", { name: /Delivery/ }));
    await waitFor(() => expect(screen.getByRole("heading", { name: "Delivery" })).toBeTruthy());
    expect(window.location.hash).toBe("#/delivery");
  });
});

describe("routes", () => {
  it("redirects the legacy #workspace hash to the workspace page", async () => {
    window.location.hash = "#workspace";
    render(<App api={makeApi()} />);
    expect(await screen.findByRole("heading", { name: "Workspace and document control" })).toBeTruthy();
    expect(window.location.hash).toBe("#/configure/workspaces");
  });

  it("keeps other legacy screens reachable under /legacy/<id>", async () => {
    window.location.hash = "#graph";
    render(<App api={makeApi()} />);
    await waitFor(() => expect(window.location.hash).toBe("#/legacy/graph"));
    expect(await screen.findByRole("combobox", { name: "Query" })).toBeTruthy();
  });

  it.each(["authoring", "pipeline", "review", "delivery"])("renders an honest placeholder for /%s", async area => {
    window.location.hash = `#/${area}`;
    render(<App api={makeApi()} />);
    expect(await screen.findByText("Not available yet")).toBeTruthy();
    expect(screen.getByText(/Slice \d/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /run|build|publish/i })).toBeNull();
  });
});

describe("design tokens", () => {
  it("defines semantic and status tokens for light and dark themes", () => {
    for (const token of ["--background", "--foreground", "--card", "--muted", "--primary", "--destructive", "--border", "--ring", "--success", "--warning", "--info"]) {
      expect(css).toContain(`${token}:`);
    }
    expect(css).toMatch(/prefers-color-scheme:\s*dark/);
    expect(css).toMatch(/\.dark\b/);
  });
  it("honours reduced motion", () => { expect(css).toMatch(/prefers-reduced-motion:\s*reduce/); });
});
