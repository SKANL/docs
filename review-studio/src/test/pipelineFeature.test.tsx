// @vitest-environment jsdom
import { act, cleanup, renderHook, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppProviders } from "../app/providers";
import type { ReviewApi } from "../api/models";
import { useRunStream } from "../features/pipeline/useRunStream";
import { makeApi } from "./authoringHarness";
import { openPipeline, page, pipelineCatalog, plan, rawRun, run, streamingApi } from "./pipelineHarness";

afterEach(() => { cleanup(); window.location.hash = ""; });

const progress = (id: string, percent: number, status = "running") => ({ type: "build", progress: percent, message: `build: ${percent}%`, run: { id, status } });
const pick = async (label: string, option: string) => {
  await userEvent.click(screen.getByRole("combobox", { name: label }));
  await userEvent.click(await screen.findByRole("option", { name: option }));
};

describe("pipeline launcher", () => {
  it("asks for a document first and links to configure when none is current", async () => {
    const { api } = streamingApi({ getCurrentDocument: async () => ({ current_document_id: null, document: null }) });
    openPipeline("/pipeline", api);
    expect(await screen.findByRole("heading", { name: "Select a document first" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open workspaces and documents" }).getAttribute("href")).toContain("/configure/workspaces");
    expect(screen.queryByRole("button", { name: "Run pipeline" })).toBeNull();
  });

  it("renders the server plan: stages and the inputs it needs", async () => {
    const planPipeline = vi.fn(async () => plan);
    const { api } = streamingApi({ planPipeline });
    openPipeline("/pipeline", api);
    const stages = await screen.findByRole("list", { name: "Pipeline stages" });
    expect(within(stages).getAllByRole("listitem").map(item => item.textContent)).toEqual(["prepare", "assemble", "build-html"]);
    expect(screen.getByText("inbox")).toBeTruthy();
    expect(planPipeline).toHaveBeenCalledWith("doc-1", { format: "docx" });
  });

  it("shows a plan error from the server instead of an empty plan", async () => {
    const { api } = streamingApi({ planPipeline: async () => { throw new Error("Unknown pipeline: document"); } });
    openPipeline("/pipeline", api);
    expect((await screen.findByRole("alert")).textContent).toContain("Unknown pipeline: document");
  });

  it("re-plans when the format changes and launches with the chosen format and policy, then opens the run", async () => {
    const planPipeline = vi.fn(async () => plan);
    const runDocument = vi.fn(async () => ({ id: "run-new", status: "queued", document_id: "doc-1", pipeline_id: "document", format: "pdf", policy: "strict", links: { self: "", progress: "", cancel: "" } }));
    const { api } = streamingApi({ planPipeline, runDocument, getRun: async (id: string) => rawRun(id, "queued") });
    openPipeline("/pipeline", api);
    await screen.findByRole("list", { name: "Pipeline stages" });
    await pick("Output format", "pdf");
    await pick("Policy", "strict");
    await waitFor(() => expect(planPipeline).toHaveBeenLastCalledWith("doc-1", { format: "pdf" }));
    await userEvent.click(screen.getByRole("button", { name: "Run pipeline" }));
    await waitFor(() => expect(runDocument).toHaveBeenCalledWith("doc-1", { format: "pdf", policy: "strict" }));
    expect(await screen.findByRole("heading", { name: "Run run-new" })).toBeTruthy();
  });

  it("launches build through the document action and opens the resulting run", async () => {
    const documentAction = vi.fn(async () => ({ id: "run-b", status: "queued" }));
    const { api } = streamingApi({ documentAction });
    openPipeline("/pipeline", api);
    await userEvent.click(await screen.findByRole("button", { name: "Build" }));
    await waitFor(() => expect(documentAction).toHaveBeenCalledWith("doc-1", "build", "ws-1", "docx"));
    expect(await screen.findByRole("heading", { name: "Run run-b" })).toBeTruthy();
  });

  it("prepare is synchronous: it reports success and stays on the page", async () => {
    const documentAction = vi.fn(async () => ({ prepared: true }));
    const { api } = streamingApi({ documentAction });
    openPipeline("/pipeline", api);
    await userEvent.click(await screen.findByRole("button", { name: "Prepare" }));
    await waitFor(() => expect(documentAction).toHaveBeenCalledWith("doc-1", "prepare", "ws-1", "docx"));
    expect(await screen.findByText("Prepared doc-1.")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Pipeline" })).toBeTruthy();
  });

  it("surfaces a launch failure with the server message", async () => {
    const { api } = streamingApi({ runDocument: async () => { throw new Error("strict and release are mutually exclusive"); } });
    openPipeline("/pipeline", api);
    await userEvent.click(await screen.findByRole("button", { name: "Run pipeline" }));
    expect(await screen.findByText(/mutually exclusive/)).toBeTruthy();
  });

  it("does not render actions whose capability is unavailable", async () => {
    const { api } = streamingApi({ documentAction: async () => ({}), getCapabilities: async () => pipelineCatalog("document.run", "document.build", "document.plan") });
    openPipeline("/pipeline", api);
    await screen.findByRole("button", { name: "Prepare" });
    expect(screen.queryByRole("button", { name: "Run pipeline" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Build" })).toBeNull();
    expect(screen.queryByRole("list", { name: "Pipeline stages" })).toBeNull();
    expect(screen.getByRole("button", { name: "Verify" })).toBeTruthy();
  });
});

describe("run list", () => {
  it("lists runs as a table linking to each detail", async () => {
    const { api } = streamingApi({ listRunPage: async () => page([run({ id: "run-1", status: "succeeded" }), run({ id: "run-2", status: "failed", format: "pdf" })]) });
    openPipeline("/pipeline", api);
    const table = await screen.findByRole("table", { name: "Runs" });
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    expect(within(table).getByRole("link", { name: "run-2" }).getAttribute("href")).toContain("/pipeline/runs/run-2");
    expect(table.textContent).toContain("failed");
    expect(table.textContent).not.toContain("{");
  });

  it("loads the next page with the server cursor and applies filters", async () => {
    const listRunPage = vi.fn(async (filters: { cursor?: string; status?: string }) => filters.cursor ? page([run({ id: "run-9" })]) : page([run({ id: "run-1" })], "c1"));
    const { api } = streamingApi({ listRunPage });
    openPipeline("/pipeline", api);
    await screen.findByRole("link", { name: "run-1" });
    await userEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(await screen.findByRole("link", { name: "run-9" })).toBeTruthy();
    expect(listRunPage).toHaveBeenCalledWith(expect.objectContaining({ cursor: "c1" }));
    expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();
    await pick("Status", "failed");
    await waitFor(() => expect(listRunPage).toHaveBeenCalledWith(expect.objectContaining({ status: "failed", cursor: undefined })));
  });

  it("filters by document", async () => {
    const listRunPage = vi.fn(async () => page([]));
    const { api } = streamingApi({ listRunPage });
    openPipeline("/pipeline", api);
    await userEvent.type(await screen.findByRole("textbox", { name: "Document" }), "doc-7");
    await waitFor(() => expect(listRunPage).toHaveBeenCalledWith(expect.objectContaining({ documentId: "doc-7" })));
  });

  it("explains an empty history", async () => {
    const { api } = streamingApi({ listRunPage: async () => page([]) });
    openPipeline("/pipeline", api);
    expect(await screen.findByText("No runs yet")).toBeTruthy();
  });
});

describe("run detail", () => {
  it("summarises the run without raw JSON and shows live progress", async () => {
    const { api, streams } = streamingApi();
    openPipeline("/pipeline/runs/run-1", api);
    expect(await screen.findByRole("heading", { name: "Run run-1" })).toBeTruthy();
    const summary = await screen.findByRole("region", { name: "Run summary" });
    expect(summary.textContent).toContain("doc-1");
    expect(summary.textContent).toContain("html");
    expect(summary.textContent).toContain("draft");
    expect(summary.textContent).not.toContain("{");
    await waitFor(() => expect(streams).toHaveLength(1));
    act(() => streams[0].emit(progress("run-1", 60)));
    await waitFor(() => expect(screen.getByRole("progressbar", { name: "Run progress" }).getAttribute("aria-valuenow")).toBe("60"));
    expect(screen.getByText("build: 60%")).toBeTruthy();
  });

  it("aborts the first stream when another run is opened and ignores its late events", async () => {
    const { api, streams } = streamingApi();
    openPipeline("/pipeline/runs/run-1", api);
    await waitFor(() => expect(streams).toHaveLength(1));
    act(() => { window.location.hash = "#/pipeline/runs/run-2"; });
    await waitFor(() => expect(streams.map(s => s.runId)).toEqual(["run-1", "run-2"]));
    expect(streams[0].signal?.aborted).toBe(true);
    expect(streams[1].signal?.aborted).toBe(false);
    act(() => streams[0].emit(progress("run-1", 90)));
    act(() => streams[1].emit(progress("run-2", 20)));
    await waitFor(() => expect(screen.getByRole("progressbar", { name: "Run progress" }).getAttribute("aria-valuenow")).toBe("20"));
    // An event for another run on the live stream is dropped too.
    act(() => streams[1].emit(progress("run-1", 99)));
    expect(screen.getByRole("progressbar", { name: "Run progress" }).getAttribute("aria-valuenow")).toBe("20");
  });

  it("aborts the stream when leaving the page", async () => {
    const { api, streams } = streamingApi();
    openPipeline("/pipeline/runs/run-1", api);
    await waitFor(() => expect(streams).toHaveLength(1));
    act(() => { window.location.hash = "#/pipeline"; });
    await waitFor(() => expect(streams[0].signal?.aborted).toBe(true));
  });

  it("stops at the terminal event and shows the receipt with a way on", async () => {
    let status = "running";
    const { api, streams } = streamingApi({ getRun: async (id: string) => rawRun(id, status) });
    openPipeline("/pipeline/runs/run-1", api);
    await waitFor(() => expect(streams).toHaveLength(1));
    status = "succeeded";
    act(() => streams[0].emit({ type: "terminal", run: { id: "run-1", status: "succeeded" } }));
    act(() => streams[0].end());
    const receipt = await screen.findByRole("region", { name: "Run receipt" });
    expect(receipt.textContent).toContain("succeeded");
    expect(within(receipt).getByRole("link", { name: "Review findings and artifacts" }).getAttribute("href")).toContain("/review");
    expect(screen.queryByRole("button", { name: "Cancel run" })).toBeNull();
    expect(streams).toHaveLength(1);
  });

  it("confirms before cancelling, and keeps running on Cancel", async () => {
    const cancelRun = vi.fn(async () => ({}));
    const { api } = streamingApi({ cancelRun });
    openPipeline("/pipeline/runs/run-1", api);
    await userEvent.click(await screen.findByRole("button", { name: "Cancel run" }));
    await userEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Cancel" }));
    expect(cancelRun).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Cancel run" }));
    await userEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Cancel this run" }));
    await waitFor(() => expect(cancelRun).toHaveBeenCalledWith("run-1"));
  });

  it("retries a failed run and follows the new run", async () => {
    const retryRun = vi.fn(async () => ({ id: "run-2", status: "queued" }));
    const { api } = streamingApi({ retryRun, getRun: async (id: string) => rawRun(id, id === "run-1" ? "failed" : "queued") });
    openPipeline("/pipeline/runs/run-1", api);
    expect(screen.queryByRole("button", { name: "Cancel run" })).toBeNull();
    await userEvent.click(await screen.findByRole("button", { name: "Retry run" }));
    await waitFor(() => expect(retryRun).toHaveBeenCalledWith("run-1"));
    expect(await screen.findByRole("heading", { name: "Run run-2" })).toBeTruthy();
  });

  it("hides cancel and retry when the server does not offer them", async () => {
    const { api } = streamingApi({ getCapabilities: async () => pipelineCatalog("run.cancel", "run.retry"), getRun: async (id: string) => rawRun(id, "failed") });
    openPipeline("/pipeline/runs/run-1", api);
    await screen.findByRole("region", { name: "Run receipt" });
    expect(screen.queryByRole("button", { name: "Retry run" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Cancel run" })).toBeNull();
  });

  it("shows a not-found state for an unknown run", async () => {
    const { api } = streamingApi({ getRun: async () => { throw new Error("Run not found"); } });
    openPipeline("/pipeline/runs/ghost", api);
    expect((await screen.findByRole("alert")).textContent).toContain("Run not found");
  });
});

describe("useRunStream", () => {
  const wrapper = (api: ReviewApi) => ({ children }: { children: ReactNode }) => <AppProviders api={api}>{children}</AppProviders>;

  it("reconnects with backoff after the server closes a non-terminal stream, then stops at terminal", async () => {
    const calls: string[] = [];
    const api = makeApi({
      streamProgress: (async (id: string, onEvent: (e: unknown) => void) => {
        calls.push(id);
        if (calls.length === 1) onEvent(progress("run-1", 10));
        else onEvent({ type: "terminal", run: { id: "run-1", status: "succeeded" } });
      }) as never,
    });
    const { result } = renderHook(() => useRunStream("run-1", { workspaceId: "ws-1", backoffMs: 1 }), { wrapper: wrapper(api) });
    await waitFor(() => expect(result.current.terminal).toBe(true));
    expect(calls).toEqual(["run-1", "run-1"]);
    expect(result.current.status).toBe("succeeded");
  });

  it("aborts and restarts when the workspace changes", async () => {
    const signals: AbortSignal[] = [];
    const api = makeApi({ streamProgress: ((_id: string, _on: unknown, signal: AbortSignal) => { signals.push(signal); return new Promise<void>(resolve => signal.addEventListener("abort", () => resolve())); }) as never });
    const { rerender } = renderHook(({ ws }) => useRunStream("run-1", { workspaceId: ws }), { wrapper: wrapper(api), initialProps: { ws: "ws-1" } });
    await waitFor(() => expect(signals).toHaveLength(1));
    rerender({ ws: "ws-2" });
    await waitFor(() => expect(signals).toHaveLength(2));
    expect(signals[0].aborted).toBe(true);
    expect(signals[1].aborted).toBe(false);
  });

  it("reports a stream failure and keeps retrying instead of going silent", async () => {
    let attempts = 0;
    const api = makeApi({ streamProgress: (async () => { attempts += 1; throw new Error("stream dropped"); }) as never });
    const { result } = renderHook(() => useRunStream("run-1", { workspaceId: "ws-1", backoffMs: 1 }), { wrapper: wrapper(api) });
    await waitFor(() => expect(result.current.error).toContain("stream dropped"));
    await waitFor(() => expect(attempts).toBeGreaterThan(1));
  });
});
