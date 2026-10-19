// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import App from "../App";
import { areas } from "../app/areas";
import type { ReviewApi } from "../api/models";
import { authoringCapabilityIds, catalogWithout, makeApi } from "./authoringHarness";
import { page, pipelineCapabilityIds, pipelineCatalog, run } from "./pipelineHarness";

afterEach(() => { cleanup(); window.location.hash = ""; localStorage.clear(); });
const open = (api: ReviewApi) => { window.location.hash = "#/"; return render(<App api={api} />); };
const finding = (over: Record<string, unknown> = {}) => ({ id: "f1", title: "t", severity: "high", status: "failed", run_id: "run-9", location: "", summary: "", owner: "", updated: "", ...over });
const homeApi = (over: Record<string, unknown> = {}) => makeApi({
  getDocumentStatus: async () => ({ succeeded: true, publication_blockers: [] }),
  listSources: async (documentId: string) => ({ document_id: documentId, items: [{ name: "a.md", path: "inbox/a.md", state: "ingested" }] }),
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
    expect(within(screen.getByRole("region", { name: "Next step" })).getAllByRole("link")).toHaveLength(1);
  });
  it("counts a source that is in the inbox but not ingested yet", async () => {
    open(homeApi({
      listSources: async (d: string) => ({ document_id: d, items: [{ name: "brief.docx", path: "inbox/brief.docx", state: "inbox" }] }),
      getDocumentClassification: async (d: string) => ({ document_id: d, items: [] }),
    }));
    await screen.findByRole("link", { name: "run-9" });
    expect(screen.queryByRole("link", { name: /Upload sources/ })).toBeNull();
  });
  it("asks for a document when none is selected", async () => {
    open(homeApi({ getCurrentDocument: async () => ({ current_document_id: null, document: null }) }));
    const next = await screen.findByRole("link", { name: /Create or select a document/ });
    expect(next.getAttribute("href")).toBe("#/configure/workspaces");
    expect(screen.getByText(/no document yet/i)).toBeTruthy();
  });
  it("asks for a workspace, not a document, when there is no workspace", async () => {
    open(homeApi({ listWorkspaces: async () => [] }));
    const next = await screen.findByRole("link", { name: /Create a workspace/ });
    expect(next.getAttribute("href")).toBe("#/configure/workspaces");
    expect(screen.getByText(/no workspace yet/i)).toBeTruthy();
    expect(screen.queryByText(/no document yet/i)).toBeNull();
  });
  it("ends on delivery when nothing else is pending", async () => {
    open(homeApi());
    expect((await screen.findByRole("link", { name: /Deliver the document/ })).getAttribute("href")).toBe("#/delivery");
  });
  it("points at sources, then pipeline, then review", async () => {
    const { unmount } = open(homeApi({ listSources: async (d: string) => ({ document_id: d, items: [] }) }));
    expect((await screen.findByRole("link", { name: /Upload sources/ })).getAttribute("href")).toBe("#/authoring/sources");
    unmount();
    const second = open(homeApi({ listRunPage: async () => page([]) }));
    expect((await screen.findByRole("link", { name: /Run the pipeline/ })).getAttribute("href")).toBe("#/pipeline");
    second.unmount();
    open(homeApi({ listFindings: async () => [finding()] }));
    expect((await screen.findByRole("link", { name: /Review findings/ })).getAttribute("href")).toBe("#/review/findings");
  });
});

describe("Home with unknown data", () => {
  it.each([
    ["sources", { listSources: async () => { throw new Error("sources down"); } }],
    ["runs", { listRunPage: async () => { throw new Error("runs down"); } }],
    ["findings", { listFindings: async () => { throw new Error("findings down"); } }],
  ])("shows an error with retry and no next action when %s fails", async (_name, over) => {
    open(homeApi(over));
    const alert = await screen.findByText(/down/);
    expect(alert).toBeTruthy();
    expect(screen.getAllByRole("button", { name: /try again/i }).length).toBeGreaterThan(0);
    expect(screen.queryByRole("region", { name: "Next step" })).toBeNull();
    expect(screen.queryByRole("link", { name: /Upload sources/ })).toBeNull();
  });
  it("shows no next action while data is still loading", async () => {
    open(homeApi({ listSources: () => new Promise(() => {}) }));
    await screen.findByRole("link", { name: "run-9" });
    expect(screen.queryByRole("region", { name: "Next step" })).toBeNull();
  });
  it("counts open findings for the current document only", async () => {
    open(homeApi({ listFindings: async () => [finding(), finding({ id: "f2", run_id: "run-other" }), finding({ id: "f3", status: "passed" })] }));
    expect(await screen.findByText(/1 open finding in this document/)).toBeTruthy();
  });
  it("does not push a review step for findings that belong to another document", async () => {
    open(homeApi({ listFindings: async () => [finding({ run_id: "run-other" })] }));
    expect(await screen.findByRole("link", { name: /Deliver the document/ })).toBeTruthy();
    expect(screen.queryByRole("link", { name: /Review findings/ })).toBeNull();
  });
});

describe("Home purpose, flow and mode chooser", () => {
  it("says what the product is for and offers the four-step flow as links", async () => {
    open(homeApi());
    const flow = await screen.findByRole("list", { name: "How it works" });
    expect(screen.getByText(/reviewable, reproducible document from your sources/i)).toBeTruthy();
    const hrefs = within(flow).getAllByRole("link").map(link => [link.textContent, link.getAttribute("href")]);
    expect(hrefs).toEqual([["Sources", "#/authoring/sources"], ["Run", "#/pipeline"], ["Review", "#/review/findings"], ["Deliver", "#/delivery"]]);
  });
  it("swaps the second step to writing in Write mode", async () => {
    localStorage.setItem("review-studio.mode", "write");
    open(homeApi());
    const flow = await screen.findByRole("list", { name: "How it works" });
    expect(within(flow).getByRole("link", { name: "Write" }).getAttribute("href")).toBe("#/authoring/sections");
  });
  it("reaches Sources upload from Home while Supervise hides the Authoring area", async () => {
    localStorage.setItem("review-studio.mode", "supervise");
    open(homeApi({ listSources: async (d: string) => ({ document_id: d, items: [] }) }));
    const nav = await screen.findByRole("navigation", { name: "Task areas" });
    expect(within(nav).queryByRole("link", { name: "Write" })).toBeNull();
    await userEvent.click(await screen.findByRole("link", { name: /Upload sources/ }));
    expect(await screen.findByRole("tab", { name: "Sources", selected: true })).toBeTruthy();
  });
  it("asks the first-run question and remembers the answer", async () => {
    open(homeApi());
    const chooser = await screen.findByRole("group", { name: "How do you want to work?" });
    expect(within(chooser).getAllByRole("button")).toHaveLength(2);
    await userEvent.click(within(chooser).getByRole("button", { name: /Write/ }));
    expect(localStorage.getItem("review-studio.mode")).toBe("write");
    await waitFor(() => expect(screen.queryByRole("group", { name: "How do you want to work?" })).toBeNull());
  });
  it("does not ask again once a mode is chosen", async () => {
    localStorage.setItem("review-studio.mode", "supervise");
    open(homeApi());
    await screen.findByRole("list", { name: "How it works" });
    expect(screen.queryByRole("group", { name: "How do you want to work?" })).toBeNull();
  });
  it("offers a plain-language explanation of finding", async () => {
    open(homeApi({ listFindings: async () => [finding()] }));
    await screen.findByText(/1 open finding in this document/);
    await userEvent.click(screen.getAllByRole("button", { name: /What is .*finding/i })[0]!);
    expect(screen.getByRole("note").textContent).toMatch(/problem/i);
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
