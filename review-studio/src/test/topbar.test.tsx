// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import type { ReviewApi } from "../api/models";

const workspaces = [{ id: "ws-a", name: "Research", root: "C:/a" }, { id: "ws-b", name: "Studio", root: "C:/b" }];
const docs = [{ id: "notes", title: "Field notes", template: "t", active: true }, { id: "plan", title: "Plan", template: "t", active: false }];

function makeApi(overrides: Partial<ReviewApi> = {}): ReviewApi {
  return {
    listFindings: async () => [], listArtifacts: async () => [],
    getGraph: async () => ({ nodes: [], edges: [] }), getGraphQuery: async () => ({ items: [], graphUnavailable: false }),
    getCapabilities: async () => ({ groups: [] }),
    listWorkspaces: async () => workspaces, selectWorkspace: async (id: string) => workspaces.find(item => item.id === id)!,
    listDocuments: async () => docs, getCurrentDocument: async () => ({ current_document_id: "notes", document: docs[0] }),
    useDocument: async (id: string) => ({ ...docs.find(item => item.id === id)!, active: true }),
    ...overrides,
  } as unknown as ReviewApi;
}
const open = (hash: string, api = makeApi()) => { window.location.hash = hash; return render(<App api={api} />); };
const topbar = () => screen.getAllByRole("banner")[0]!; // page headers also render <header>; the topbar comes first

afterEach(() => { cleanup(); window.location.hash = ""; localStorage.clear(); document.documentElement.className = ""; });

describe("topbar", () => {
  it("names the product and no longer renders the foundation footer", () => {
    open("#/");
    expect(within(topbar()).getByText("Studio")).toBeTruthy();
    expect(screen.queryByText("Review Studio foundation")).toBeNull();
    expect(screen.queryByRole("contentinfo")).toBeNull();
  });

  it("shows the active workspace and document from every screen", async () => {
    for (const hash of ["#/", "#/delivery", "#/configure"]) {
      cleanup();
      open(hash);
      await waitFor(() => expect(within(topbar()).getByRole("combobox", { name: "Workspace" }).textContent).toContain("Research"));
      await waitFor(() => expect(within(topbar()).getByRole("combobox", { name: "Document" }).textContent).toContain("Field notes"));
    }
  });

  it("switches workspace through the same API call Configure uses", async () => {
    const selectWorkspace = vi.fn(async (id: string) => workspaces.find(item => item.id === id)!);
    open("#/delivery", makeApi({ selectWorkspace }));
    const box = await within(topbar()).findByRole("combobox", { name: "Workspace" });
    await waitFor(() => expect(box.textContent).toContain("Research"));
    await userEvent.click(box);
    await userEvent.click(await screen.findByRole("option", { name: "Studio" }));
    await waitFor(() => expect(selectWorkspace).toHaveBeenCalledWith("ws-b"));
  });

  it("switches document inside the active workspace", async () => {
    const useDocument = vi.fn(async (id: string) => ({ ...docs.find(item => item.id === id)!, active: true }));
    open("#/review", makeApi({ useDocument }));
    const box = await within(topbar()).findByRole("combobox", { name: "Document" });
    await waitFor(() => expect(box.textContent).toContain("Field notes"));
    await userEvent.click(box);
    await userEvent.click(await screen.findByRole("option", { name: "Plan" }));
    await waitFor(() => expect(useDocument).toHaveBeenCalledWith("plan", "ws-a"));
  });

  it("says so when there is no workspace", async () => {
    open("#/", makeApi({ listWorkspaces: async () => [] }));
    expect((await within(topbar()).findByRole("combobox", { name: "Workspace" })).textContent).toContain("No workspace");
  });

  it("offers an accessible Supervise | Write switch that persists", async () => {
    open("#/");
    const group = within(topbar()).getByRole("group", { name: "Working mode" });
    const supervise = within(group).getByRole("button", { name: "Supervise" });
    const write = within(group).getByRole("button", { name: "Write" });
    expect(supervise.getAttribute("aria-pressed")).toBe("true");
    expect(write.getAttribute("aria-pressed")).toBe("false");
    await userEvent.click(write);
    expect(write.getAttribute("aria-pressed")).toBe("true");
    expect(localStorage.getItem("review-studio.mode")).toBe("write");
  });

  it("toggles Advanced with a labelled switch", async () => {
    open("#/");
    const toggle = within(topbar()).getByRole("switch", { name: "Advanced" });
    expect(toggle.getAttribute("aria-checked")).toBe("false");
    await userEvent.click(toggle);
    expect(toggle.getAttribute("aria-checked")).toBe("true");
  });

  it("switches the interface language and persists it", async () => {
    open("#/");
    await userEvent.click(within(topbar()).getByRole("button", { name: "Language" }));
    expect(within(topbar()).getByRole("group", { name: "Modo de trabajo" })).toBeTruthy();
    expect(within(topbar()).getByRole("switch", { name: "Avanzado" })).toBeTruthy();
    expect(localStorage.getItem("review-studio.locale")).toBe("es");
  });

  it("toggles the theme", async () => {
    open("#/");
    await userEvent.click(within(topbar()).getByRole("button", { name: "Theme" }));
    await waitFor(() => expect(document.documentElement.classList.contains("dark")).toBe(true));
  });

  it("keeps the skip link and landmarks", () => {
    open("#/");
    expect(screen.getByRole("link", { name: "Skip to content" })).toBeTruthy();
    expect(screen.getByRole("main")).toBeTruthy();
    expect(screen.getAllByRole("navigation").length).toBeGreaterThan(0);
  });
});
