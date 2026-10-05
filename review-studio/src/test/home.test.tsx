// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import App from "../App";
import { areas } from "../app/areas";
import type { ReviewApi } from "../api/models";
import { authoringCapabilityIds, catalogWithout, makeApi } from "./authoringHarness";
import { page, pipelineCapabilityIds, pipelineCatalog, run } from "./pipelineHarness";

afterEach(() => { cleanup(); window.location.hash = ""; });
const open = (api: ReviewApi) => { window.location.hash = "#/"; return render(<App api={api} />); };
const homeApi = (over: Record<string, unknown> = {}) => makeApi({
  getDocumentStatus: async () => ({ succeeded: true, publication_blockers: [] }),
  listAssets: async (documentId: string) => ({ document_id: documentId, kind: "source", items: [{ name: "a.md" }] }),
  listRunPage: async () => page([run({ id: "run-9", status: "succeeded" })]),
  ...over,
} as never);

describe("Home", () => {
  it("shows readiness, server blockers, recent runs and one next action", async () => {
    open(homeApi({ getDocumentStatus: async () => ({ succeeded: false, publication_blockers: ["Missing legal review"] }) }));
    expect(await screen.findByText("Missing legal review")).toBeTruthy();
    expect(screen.getByText("Needs attention")).toBeTruthy();
    const link = await screen.findByRole("link", { name: "run-9" });
    expect(link.getAttribute("href")).toBe("#/pipeline/runs/run-9");
    expect(within(screen.getByRole("region", { name: "Next safe action" })).getAllByRole("link")).toHaveLength(1);
  });
  it("asks for a document when none is selected", async () => {
    open(homeApi({ getCurrentDocument: async () => ({ current_document_id: null, document: null }) }));
    const next = await screen.findByRole("link", { name: /Create a document/ });
    expect(next.getAttribute("href")).toBe("#/configure/workspaces");
  });
  it("points at sources, then pipeline, then review", async () => {
    const { unmount } = open(homeApi({ listAssets: async (d: string) => ({ document_id: d, kind: "source", items: [] }) }));
    expect((await screen.findByRole("link", { name: /Add sources/ })).getAttribute("href")).toBe("#/authoring/sources");
    unmount();
    const second = open(homeApi({ listRunPage: async () => page([]) }));
    expect((await screen.findByRole("link", { name: /Run the pipeline/ })).getAttribute("href")).toBe("#/pipeline");
    second.unmount();
    open(homeApi({ listFindings: async () => [{ id: "f1", title: "t", severity: "high", status: "failed", location: "", summary: "", owner: "", updated: "" }] }));
    expect((await screen.findByRole("link", { name: /Review findings/ })).getAttribute("href")).toBe("#/review/findings");
  });
});

describe("every sidebar area renders a real page", () => {
  it.each(areas.map(area => [area.label, area.path] as const))("%s", async (label, path) => {
    window.location.hash = `#${path}`;
    render(<App api={homeApi({ getCapabilities: async () => ({ groups: [...catalogWithout().groups, ...pipelineCatalog().groups] }) })} />);
    expect(await screen.findByRole("heading", { level: 1, name: label })).toBeTruthy();
    await waitFor(() => expect(screen.queryByText(/Not available yet/i)).toBeNull());
    expect(within(document.body).queryByText(/legacy screens/i)).toBeNull();
  });
});
void authoringCapabilityIds; void pipelineCapabilityIds;
