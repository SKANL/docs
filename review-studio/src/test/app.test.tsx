// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import App from "../App";
import { ReviewApiClient } from "../api/client";
import type { ReviewApi } from "../api/models";

const apiFrom = (fetch: typeof globalThis.fetch): ReviewApi => {
  const client = new ReviewApiClient({ baseUrl: "https://review.test/v1", fetch });
  return {
    listRuns: () => client.listRuns(),
    listFindings: () => client.listFindings(),
    listArtifacts: () => client.listArtifacts(),
    getPassport: id => client.getPassport(id), getGraph: () => client.getGraph(), getGraphQuery: (q, id) => client.getGraphQuery(q, id),
    listTemplates: () => client.listTemplates(), listBaselines: () => client.listBaselines(),
    listRevisions: () => client.listRevisions(), listPublications: () => client.listPublications(),
  };
};

afterEach(() => {
  cleanup();
  window.location.hash = "";
});

describe("semantic graph explorer", () => {
  it("exposes keyboard-friendly domain query controls and deterministic empty results", async () => {
    window.location.hash = "#graph";
    render(<App api={apiFrom(async () => new Response(JSON.stringify({ items: [] }), { headers: { "content-type": "application/json" } }))} />);

    expect(screen.getByRole("combobox", { name: "Query" })).toBeTruthy();
    fireEvent.change(screen.getByRole("combobox", { name: "Query" }), {
      target: { value: "unused_references" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run query" }));

    await waitFor(() => expect(screen.getByText("No matching nodes were returned.")).toBeTruthy());
    expect(screen.getByText(/not attestations/i)).toBeTruthy();
  });

  it("surfaces authenticated API failures instead of rendering demo data", async () => {
    window.location.hash = "#runs";
    const api = apiFrom(async () => new Response(JSON.stringify({ code: "authentication_required", message: "Authentication required" }), { status: 401, headers: { "x-request-id": "req-auth" } }));
    render(<App api={api} />);

    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("Authentication required"));
    expect(screen.getByRole("alert").textContent).toContain("req-auth");
    expect(screen.queryByText("run-2026-09-15-1432")).toBeNull();
  });
});

describe("overview", () => {
  it("loads overview metrics from the latest API run instead of demo values", async () => {
    window.location.hash = "#overview";
    const api = apiFrom(async input => {
      const path = new URL(input.toString()).pathname;
      const payloads: Record<string, unknown> = {
        "/v1/runs": { items: [
          { id: "run-old", document: "Old case", template: "srs", startedAt: "2026-09-18T10:00:00Z", duration: "1m", status: "passed", findings: 1, artifactCount: 2 },
          { id: "run-new", document: "Current case", template: "srs", startedAt: "2026-09-19T10:00:00Z", duration: "2m", status: "warnings", findings: 2, artifactCount: 3 },
        ] },
        "/v1/findings": { items: [{ id: "finding-1", title: "Missing locator", severity: "high", status: "warnings", location: "overview", summary: "Needs evidence", owner: "reviewer", updated: "today" }] },
        "/v1/artifacts": { items: [{ id: "artifact-1", name: "current.docx", kind: "DOCX", size: "10 KB", status: "passed", checksum: "sha256:test" }] },
        "/v1/runs/run-new/passport": { id: "passport-new", runId: "run-new", verifiedAt: "today", coverage: 84, attestations: 4, sources: 3, claims: 5, unresolved: 1 },
      };
      return new Response(JSON.stringify(payloads[path]), { headers: { "content-type": "application/json" } });
    });

    render(<App api={api} />);

    await waitFor(() => expect(screen.getByText("Current case")).toBeTruthy());
    expect(screen.getAllByText("run-new").length).toBeGreaterThan(0);
    expect(screen.getByText("84%" )).toBeTruthy();
    expect(screen.queryByText(/northstar/i)).toBeNull();
    expect(screen.queryByText("run-2026-09-15-1432")).toBeNull();
  });

  it("reports empty overview resources and API failures honestly", async () => {
    window.location.hash = "#overview";
    const api = apiFrom(async input => {
      const path = new URL(input.toString()).pathname;
      if (path === "/v1/runs") return new Response(JSON.stringify({ code: "server_error", message: "Runs unavailable" }), { status: 503 });
      return new Response(JSON.stringify({ items: [] }), { headers: { "content-type": "application/json" } });
    });

    render(<App api={api} />);

    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("Runs unavailable"));
    expect(screen.getAllByText("No runs available.").length).toBeGreaterThan(0);
    expect(screen.getByText("No findings available.")).toBeTruthy();
    expect(screen.getByText("No artifacts available.")).toBeTruthy();
    expect(screen.getAllByText("No evidence passport available.").length).toBeGreaterThan(0);
  });
});
