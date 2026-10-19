// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import App from "../App";
import { areas, visibleAreas } from "../app/areas";
import type { ReviewApi } from "../api/models";

function makeApi(): ReviewApi {
  return {
    listFindings: async () => [], listArtifacts: async () => [], listWorkspaces: async () => [],
    getCapabilities: async () => ({ groups: [] }),
    getGraph: async () => ({ nodes: [], edges: [] }), getGraphQuery: async () => ({ items: [], graphUnavailable: false }),
  } as unknown as ReviewApi;
}
function open(hash: string, stored: { mode?: string; advanced?: string } = {}) {
  if (stored.mode) localStorage.setItem("review-studio.mode", stored.mode);
  if (stored.advanced) localStorage.setItem("review-studio.advanced", stored.advanced);
  window.location.hash = hash;
  return render(<App api={makeApi()} />);
}
const names = (nav: HTMLElement) => within(nav).getAllByRole("link").map(link => link.textContent);

afterEach(() => { cleanup(); localStorage.clear(); window.location.hash = ""; });

describe("area visibility rule", () => {
  const ids = (mode: "supervise" | "write", advanced: boolean) => visibleAreas(mode, advanced).map(area => area.id);
  it("shows at most four areas by default", () => {
    expect(ids("supervise", false)).toEqual(["home", "pipeline", "review", "delivery"]);
    expect(visibleAreas("supervise", false)).toHaveLength(4);
  });
  it("adds authoring in write mode and tools plus configuration under advanced", () => {
    expect(ids("write", false)).toContain("authoring");
    expect(ids("supervise", false)).not.toContain("authoring");
    expect(ids("supervise", true)).toEqual(expect.arrayContaining(["tools", "configure"]));
    expect(ids("supervise", true)).not.toContain("authoring");
    expect(visibleAreas("write", true)).toHaveLength(areas.length);
  });
});

describe("navigation by mode", () => {
  it("lists four task areas in Supervise and no specialist tools", async () => {
    open("#/");
    const nav = await screen.findByRole("navigation", { name: "Task areas" });
    expect(names(nav)).toEqual(["Home", "Run", "Review", "Deliver"]);
    expect(screen.queryByRole("navigation", { name: "Specialist tools" })).toBeNull();
  });
  it("adds Write in write mode", async () => {
    open("#/", { mode: "write" });
    expect(names(await screen.findByRole("navigation", { name: "Task areas" }))).toEqual(["Home", "Write", "Run", "Review", "Deliver"]);
  });
  it("adds technical configuration and tools under Advanced", async () => {
    open("#/", { advanced: "true" });
    expect(names(await screen.findByRole("navigation", { name: "Task areas" }))).toEqual(["Home", "Run", "Review", "Deliver", "Technical configuration"]);
    expect(names(screen.getByRole("navigation", { name: "Specialist tools" }))).toEqual(["Tools"]);
  });
  it("follows a mode change made in the topbar", async () => {
    open("#/");
    await userEvent.click(within(screen.getAllByRole("banner")[0]!).getByRole("button", { name: "Write" }));
    expect(names(screen.getByRole("navigation", { name: "Task areas" }))).toContain("Write");
  });
  it("hides hidden areas from the palette but keeps the visible ones", async () => {
    open("#/");
    await userEvent.click(screen.getByRole("button", { name: "Open command menu" }));
    const palette = await screen.findByRole("dialog", { name: /command palette/i });
    expect(within(palette).getByText("Run")).toBeTruthy();
    expect(within(palette).queryByText("Write")).toBeNull();
    expect(within(palette).queryByText("Tools")).toBeNull();
  });
  it("lists every area in the palette under write + Advanced", async () => {
    open("#/", { mode: "write", advanced: "true" });
    await userEvent.click(screen.getByRole("button", { name: "Open command menu" }));
    const palette = await screen.findByRole("dialog", { name: /command palette/i });
    for (const label of ["Home", "Write", "Run", "Review", "Deliver", "Tools", "Technical configuration"]) expect(within(palette).getByText(label)).toBeTruthy();
  });
  it.each([["#/authoring/sources", "Authoring"], ["#/tools", "Tools"], ["#/configure", "Configure"]])("still resolves hidden area %s by URL", async (hash, heading) => {
    open(hash);
    expect(await screen.findByRole("heading", { level: 1, name: heading }, { timeout: 5000 })).toBeTruthy();
    await waitFor(() => expect(screen.queryByText("Page not found")).toBeNull());
  });
});
