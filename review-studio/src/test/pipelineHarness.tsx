import { render } from "@testing-library/react";
import App from "../App";
import type { Capability, ReviewApi } from "../api/models";
import type { PipelinePlan, RunPage, RunRecord } from "../api/domains/pipeline";
import { makeApi } from "./authoringHarness";

const cap = (id: string, status: Capability["status"] = "available"): Capability => ({
  id, cli_command: id.replace(".", " "), route: status === "available" ? "POST /v2/x" : null, scopes: [], surface: "web+desktop", slice: "S3", status,
});
export const pipelineCapabilityIds = ["document.plan", "document.run", "document.prepare", "document.build", "document.verify", "run.list", "run.show", "run.watch", "run.cancel", "run.retry"];
export const pipelineCatalog = (...missing: string[]) => ({ groups: [{ id: "pipeline", capabilities: pipelineCapabilityIds.map(id => cap(id, missing.includes(id) ? "planned" : "available")) }] });

export const plan: PipelinePlan = { document_id: "doc-1", pipeline_id: "document", stages: ["prepare", "assemble", "build-html"], external_artifacts: ["inbox"], contracts: [] };
export const run = (over: Partial<RunRecord> = {}): RunRecord => ({ id: "run-1", status: "running", documentId: "doc-1", pipelineId: "document", format: "html", policy: "draft", createdAt: "2026-01-01T00:00:00Z", ...over });
export const page = (items: RunRecord[], nextCursor?: string): RunPage => ({ items, nextCursor });
export const rawRun = (id: string, status = "running") => ({ id, status, created_at: "2026-01-01T00:00:00Z", payload: { document_id: "doc-1", format: "html", policy: "draft", pipeline_id: "document" } });

/** An API whose streams stay open until their signal aborts; tests push events through `emit`. */
export function streamingApi(overrides: Partial<ReviewApi> = {}) {
  const streams: Array<{ runId: string; signal?: AbortSignal; emit(event: Record<string, unknown>): void; end(): void }> = [];
  const api = makeApi({
    getCapabilities: async () => pipelineCatalog(),
    planPipeline: async () => plan,
    listRunPage: async () => page([run()]),
    getRun: async (id: string) => rawRun(id),
    streamProgress: (runId: string, onEvent: (event: { type: string }) => void, signal?: AbortSignal) => new Promise<void>(resolve => {
      streams.push({ runId, signal, emit: event => onEvent(event as never), end: resolve });
      signal?.addEventListener("abort", () => resolve(), { once: true });
    }),
    ...overrides,
  } as Partial<ReviewApi>);
  return { api, streams };
}

export function openPipeline(path: string, api: ReviewApi) {
  window.location.hash = `#${path}`;
  return render(<App api={api} />);
}
