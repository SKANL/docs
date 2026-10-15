// @vitest-environment jsdom
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/errors";
import { artifact, bundle, finding, inspected, makeReviewApi, openReview, reviewCatalog } from "./reviewHarness";

// Passport, digests and other technical detail only render under Advanced; these tests exercise the full view.
beforeEach(() => localStorage.setItem("review-studio.advanced", "true"));
afterEach(() => { cleanup(); window.location.hash = ""; localStorage.clear(); });

const pick = async (label: string, option: string) => {
  await userEvent.click(screen.getByRole("combobox", { name: label }));
  await userEvent.click(await screen.findByRole("option", { name: option }));
};

describe("findings", () => {
  it("lists findings in a table with severity and filters them", async () => {
    const api = makeReviewApi({ listFindings: async () => [finding(), finding({ id: "f-2", title: "Low contrast", severity: "low" })] });
    openReview("/review/findings", api);
    const table = await screen.findByRole("table", { name: "Findings" });
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    await userEvent.type(screen.getByRole("textbox", { name: "Filter findings" }), "contrast");
    expect(within(table).getAllByRole("row")).toHaveLength(2);
    expect(table.textContent).not.toContain("{");
  });

  it("navigates from a finding to its run evidence and its authoring section", async () => {
    const getRunEvidence = vi.fn(async () => bundle());
    const api = makeReviewApi({ getRunEvidence, listFindings: async () => [finding({ section: "intro", evidence: "Input file notes.md line 4" })] });
    openReview("/review/findings", api);
    await userEvent.click(await screen.findByRole("link", { name: "f-1" }));
    const detail = await screen.findByRole("region", { name: "Finding detail" });
    expect(detail.textContent).toContain("Input file notes.md line 4");
    expect(within(detail).getByRole("link", { name: "Open in authoring section" }).getAttribute("href")).toContain("/authoring/sections?section=intro");
    await userEvent.click(within(detail).getByRole("link", { name: "Open run evidence" }));
    expect(await screen.findByRole("heading", { name: "Evidence for run-1" })).toBeTruthy();
    expect(getRunEvidence).toHaveBeenCalledWith("run-1");
  });

  it("explains an empty inbox", async () => {
    openReview("/review/findings", makeReviewApi({ listFindings: async () => [] }));
    expect(await screen.findByText("No findings")).toBeTruthy();
  });
});

describe("evidence", () => {
  it("shows digests, the passport summary and artifacts without raw JSON", async () => {
    openReview("/review/evidence/run-1", makeReviewApi());
    const digest = await screen.findByRole("region", { name: "Evidence digest" });
    expect(digest.textContent).toContain("f".repeat(64));
    const passport = screen.getByRole("region", { name: "Passport summary" });
    expect(passport.textContent).toContain("build-html");
    expect(passport.textContent).toContain("run-0");
    expect(screen.getByRole("link", { name: "a-1" }).getAttribute("href")).toContain("/review/artifacts/a-1");
    expect(document.body.textContent).not.toContain('"entries"');
  });

  it("hides the whole evidence view when the capability is missing", async () => {
    openReview("/review/evidence/run-1", makeReviewApi({ getCapabilities: async () => reviewCatalog("document.evidence") }));
    expect(await screen.findByText(/not available on this server/i)).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Evidence digest" })).toBeNull();
  });
});

describe("artifacts and previews", () => {
  const withPreviews = (list: Array<Record<string, unknown>>) => makeReviewApi({ listArtifactPreviews: async () => list });

  it("renders preview images from the server preview url", async () => {
    openReview("/review/artifacts/a-1", withPreviews([{ id: "p-1" }, { id: "p-2" }]));
    const images = await screen.findAllByRole("img");
    expect(images.map(img => img.getAttribute("src"))).toEqual(["https://review.test/v2/runs/run-1/previews/p-1", "https://review.test/v2/runs/run-1/previews/p-2"]);
  });

  it("says honestly when no previews exist", async () => {
    openReview("/review/artifacts/a-1", withPreviews([]));
    expect(await screen.findByText(/No rendered previews/)).toBeTruthy();
    expect(screen.queryByRole("img")).toBeNull();
  });

  it("degrades when the preview list cannot be loaded", async () => {
    openReview("/review/artifacts/a-1", makeReviewApi({ listArtifactPreviews: async () => { throw new Error("boom"); } }));
    expect(await screen.findByText(/Previews could not be loaded/)).toBeTruthy();
  });

  it("degrades when an image fails to load", async () => {
    openReview("/review/artifacts/a-1", withPreviews([{ id: "p-1" }]));
    const image = await screen.findByRole("img");
    image.dispatchEvent(new Event("error"));
    expect(await screen.findByText(/Preview image unavailable/)).toBeTruthy();
  });

  it("inspects an artifact into a structured report", async () => {
    const inspectArtifact = vi.fn(async () => inspected);
    openReview("/review/artifacts/a-1", makeReviewApi({ inspectArtifact }));
    await userEvent.click(await screen.findByRole("button", { name: "Inspect artifact" }));
    const panel = await screen.findByRole("region", { name: "Inspection" });
    expect(panel.textContent).toContain("output/report.docx");
    expect(panel.textContent).toContain("2048");
    expect(panel.textContent).toContain("9".repeat(64));
    expect(inspectArtifact).toHaveBeenCalledWith("a-1");
  });

  it("surfaces an inspect failure from the server", async () => {
    openReview("/review/artifacts/a-1", makeReviewApi({ inspectArtifact: async () => { throw new ApiError("Artifact file is not materialized", 409, "artifact_unavailable"); } }));
    await userEvent.click(await screen.findByRole("button", { name: "Inspect artifact" }));
    expect(await screen.findByText(/not materialized/)).toBeTruthy();
  });

  it("hides inspect when its capability is missing", async () => {
    openReview("/review/artifacts/a-1", makeReviewApi({ getCapabilities: async () => reviewCatalog("document.inspect") }));
    await screen.findByRole("heading", { name: "report.docx" });
    expect(screen.queryByRole("button", { name: "Inspect artifact" })).toBeNull();
  });
});

describe("capability-gated read surfaces", () => {
  it.each([["findings", "findings.list", "listFindings"], ["artifacts", "artifacts.list", "listArtifacts"], ["baselines", "baselines.list", "listBaselines"], ["graph", "graph.read", "getGraph"]])("does not load %s when the server does not list the capability", async (tab, id, method) => {
    const load = vi.fn(async () => []);
    openReview(`/review/${tab}`, makeReviewApi({ getCapabilities: async () => reviewCatalog(id), [method]: load }));
    expect(await screen.findByText(/is not available on this server/)).toBeTruthy();
    expect(load).not.toHaveBeenCalled();
  });
});

describe("baseline promotion", () => {
  const open = async (api = makeReviewApi()) => {
    openReview("/review/evidence/run-1", api);
    await userEvent.click(await screen.findByRole("button", { name: "Promote to baseline" }));
    return screen.findByRole("dialog");
  };
  const done = { run_id: "run-1", name: "main", destination: "baselines/main", replaced: false, pages: [{ name: "p1.png", sha256: "a".repeat(64) }] };

  it("confirms with the chosen name and shows the promoted pages", async () => {
    const promoteBaseline = vi.fn(async () => done);
    const dialog = await open(makeReviewApi({ promoteBaseline }));
    await userEvent.clear(within(dialog).getByRole("textbox", { name: "Baseline name" }));
    await userEvent.type(within(dialog).getByRole("textbox", { name: "Baseline name" }), "main");
    await userEvent.click(within(dialog).getByRole("button", { name: "Promote baseline" }));
    await waitFor(() => expect(promoteBaseline).toHaveBeenCalledWith({ runId: "run-1", name: "main", update: false }));
    expect(await within(dialog).findByText("p1.png")).toBeTruthy();
  });

  it("requires a second explicit confirmation before overwriting", async () => {
    const promoteBaseline = vi.fn(async (input: { update?: boolean }) => {
      if (!input.update) throw new ApiError("Baseline already exists; pass update to replace it", 409, "baseline_exists");
      return { ...done, replaced: true };
    });
    const dialog = await open(makeReviewApi({ promoteBaseline }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Promote baseline" }));
    expect(await within(dialog).findByText(/already exists/)).toBeTruthy();
    expect(promoteBaseline).toHaveBeenCalledTimes(1);
    await userEvent.click(within(dialog).getByRole("button", { name: "Replace existing baseline" }));
    await waitFor(() => expect(promoteBaseline).toHaveBeenLastCalledWith({ runId: "run-1", name: "run-1", update: true }));
    expect(await within(dialog).findByText(/replaced/i)).toBeTruthy();
  });

  it("surfaces previews_unavailable instead of pretending success", async () => {
    const dialog = await open(makeReviewApi({ promoteBaseline: async () => { throw new ApiError("The run has no rendered previews to promote", 409, "previews_unavailable"); } }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Promote baseline" }));
    expect(await within(dialog).findByText(/no rendered previews to promote/)).toBeTruthy();
    expect(within(dialog).queryByRole("button", { name: "Replace existing baseline" })).toBeNull();
  });

  it("offers no promotion without the capability", async () => {
    openReview("/review/evidence/run-1", makeReviewApi({ getCapabilities: async () => reviewCatalog("document.baseline") }));
    await screen.findByRole("region", { name: "Evidence digest" });
    expect(screen.queryByRole("button", { name: "Promote to baseline" })).toBeNull();
  });
});

describe("baselines", () => {
  it("lists baselines and shows readable details", async () => {
    const api = makeReviewApi({
      listBaselines: async () => [{ id: "main", name: "main", scope: "workspace", created: "2026-01-01", status: "passed", delta: "-" }],
      getBaseline: async () => ({ id: "main", pages: 3, note: "approved" }),
    });
    openReview("/review/baselines", api);
    expect(await screen.findByRole("table", { name: "Baselines" })).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Details for main" }));
    const detail = await screen.findByRole("region", { name: "Baseline detail" });
    expect(detail.textContent).toContain("approved");
  });

  it("explains an empty list and points to promotion", async () => {
    openReview("/review/baselines", makeReviewApi());
    expect(await screen.findByText("No baselines yet")).toBeTruthy();
  });
});

describe("diff", () => {
  const two = [artifact(), artifact({ id: "a-2", name: "report-v2.docx" })];
  const diffResult = (lines: string[], same = false) => ({ same, left: { ...inspected, path: "o/a.docx" }, right: { ...inspected, path: "o/b.docx" }, text_diff: lines });

  it("compares the two chosen artifacts", async () => {
    const diffArtifacts = vi.fn(async () => diffResult(["--- o/a.docx", "+++ o/b.docx", "-old line", "+new line"]));
    openReview("/review/diff", makeReviewApi({ listArtifacts: async () => two, diffArtifacts }));
    await screen.findByRole("combobox", { name: "Left artifact" });
    await pick("Left artifact", "report.docx");
    await pick("Right artifact", "report-v2.docx");
    await userEvent.click(screen.getByRole("button", { name: "Compare" }));
    await waitFor(() => expect(diffArtifacts).toHaveBeenCalledWith("a-1", "a-2"));
    const view = await screen.findByRole("region", { name: "Differences" });
    expect(view.textContent).toContain("+new line");
  });

  it("truncates a long diff until the user asks for all of it", async () => {
    const lines = Array.from({ length: 450 }, (_, i) => `+line ${i}`);
    openReview("/review/diff", makeReviewApi({ listArtifacts: async () => two, diffArtifacts: async () => diffResult(lines) }));
    await screen.findByRole("combobox", { name: "Left artifact" });
    await pick("Left artifact", "report.docx");
    await pick("Right artifact", "report-v2.docx");
    await userEvent.click(screen.getByRole("button", { name: "Compare" }));
    const view = await screen.findByRole("region", { name: "Differences" });
    expect(view.textContent).toContain("+line 0");
    expect(view.textContent).not.toContain("+line 449");
    await userEvent.click(screen.getByRole("button", { name: "Show all 450 lines" }));
    expect(view.textContent).toContain("+line 449");
  });

  it("says when the artifacts are identical", async () => {
    openReview("/review/diff", makeReviewApi({ listArtifacts: async () => two, diffArtifacts: async () => diffResult([], true) }));
    await screen.findByRole("combobox", { name: "Left artifact" });
    await pick("Left artifact", "report.docx");
    await pick("Right artifact", "report-v2.docx");
    await userEvent.click(screen.getByRole("button", { name: "Compare" }));
    expect(await screen.findByText(/identical/i)).toBeTruthy();
  });

  it("hides compare when the capability is missing", async () => {
    openReview("/review/diff", makeReviewApi({ listArtifacts: async () => two, getCapabilities: async () => reviewCatalog("document.diff") }));
    expect(await screen.findByText(/not available on this server/i)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Compare" })).toBeNull();
  });
});

describe("qa", () => {
  const result = (over: Record<string, unknown> = {}) => ({ document_id: "doc-1", docx: "o.docx", strict: false, passed: true, message: "All pages render", degraded: false, degraded_reason: null, report: null, ...over });

  it("runs qa with the strict toggle and shows the verdict", async () => {
    const runQaDocx = vi.fn(async () => result({ strict: true }));
    openReview("/review/qa", makeReviewApi({ runQaDocx }));
    await userEvent.click(await screen.findByRole("switch", { name: "Strict mode" }));
    await userEvent.click(screen.getByRole("button", { name: "Run DOCX QA" }));
    await waitFor(() => expect(runQaDocx).toHaveBeenCalledWith("doc-1", { strict: true }));
    expect(await screen.findByText("All pages render")).toBeTruthy();
  });

  it("surfaces a degraded result with its reason on its own line", async () => {
    openReview("/review/qa", makeReviewApi({ runQaDocx: async () => result({ passed: false, degraded: true, degraded_reason: "LibreOffice was not found" }) }));
    await userEvent.click(await screen.findByRole("button", { name: "Run DOCX QA" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Degraded");
    expect(alert.textContent).toContain("LibreOffice was not found");
  });

  it("shows docx_unavailable from the server", async () => {
    openReview("/review/qa", makeReviewApi({ runQaDocx: async () => { throw new ApiError("Build the document first", 409, "docx_unavailable"); } }));
    await userEvent.click(await screen.findByRole("button", { name: "Run DOCX QA" }));
    expect(await screen.findByText(/Build the document first/)).toBeTruthy();
  });

  it("applies corrections only after confirmation", async () => {
    const applyCorrections = vi.fn(async () => ({ document_id: "doc-1", applied: 2 }));
    openReview("/review/qa", makeReviewApi({ applyCorrections }));
    await userEvent.click(await screen.findByRole("button", { name: "Apply corrections" }));
    expect(applyCorrections).not.toHaveBeenCalled();
    await userEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Cancel" }));
    expect(applyCorrections).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Apply corrections" }));
    await userEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Apply corrections" }));
    await waitFor(() => expect(applyCorrections).toHaveBeenCalledWith("doc-1"));
    expect(await screen.findByText("Applied 2 corrections.")).toBeTruthy();
  });

  it("hides qa and corrections actions without their capabilities", async () => {
    openReview("/review/qa", makeReviewApi({ getCapabilities: async () => reviewCatalog("qa-docx", "apply-corrections") }));
    await screen.findByRole("heading", { name: "Review" });
    await waitFor(() => expect(screen.queryByRole("button", { name: "Run DOCX QA" })).toBeNull());
    expect(screen.queryByRole("button", { name: "Apply corrections" })).toBeNull();
  });

  it("asks for a document when none is current", async () => {
    openReview("/review/qa", makeReviewApi({ getCurrentDocument: async () => ({ current_document_id: null, document: null }) }));
    expect(await screen.findByText("Select a document first")).toBeTruthy();
  });
});

describe("graph", () => {
  it("shows an honest empty-graph state", async () => {
    openReview("/review/graph", makeReviewApi());
    expect(await screen.findByText("The semantic graph is empty")).toBeTruthy();
  });

  it("runs a graph query and lists the matches", async () => {
    const getGraphQuery = vi.fn(async () => ({ items: [{ id: "c1", kind: "claim", label: "Revenue grew", confidence: 0.5 }] }));
    openReview("/review/graph", makeReviewApi({ getGraphQuery, getGraph: async () => ({ nodes: [{ id: "c1", label: "Revenue grew", type: "claim" as const, confidence: 0.5, x: 1, y: 1 }], edges: [] }) }));
    await userEvent.click(await screen.findByRole("button", { name: "Run query" }));
    await waitFor(() => expect(getGraphQuery).toHaveBeenCalledWith("claims_without_evidence", undefined));
    expect(await screen.findByRole("table", { name: "Query results" })).toBeTruthy();
  });

  it("requires an id for queries that need one", async () => {
    const getGraphQuery = vi.fn(async () => ({ items: [] }));
    openReview("/review/graph", makeReviewApi({ getGraphQuery }));
    await screen.findByText("The semantic graph is empty");
    await pick("Query", "Findings affected by revision");
    await userEvent.click(screen.getByRole("button", { name: "Run query" }));
    expect(await screen.findByText(/Revision id is required/)).toBeTruthy();
    expect(getGraphQuery).not.toHaveBeenCalled();
  });

  it("offers the traceability queries", async () => {
    openReview("/review/graph", makeReviewApi());
    await userEvent.click(await screen.findByRole("combobox", { name: "Query" }));
    for (const label of ["Stale artifacts", "Source impact", "Requirement coverage"]) expect(await screen.findByRole("option", { name: label })).toBeTruthy();
  });

  it("tells no data apart from an empty result", async () => {
    const getGraphQuery = vi.fn()
      .mockResolvedValueOnce({ items: [], noData: true, coverage: { claim: 0, evidence: 0 } })
      .mockResolvedValueOnce({ items: [], noData: false, coverage: { claim: 3, evidence: 1 } });
    openReview("/review/graph", makeReviewApi({ getGraphQuery }));
    await userEvent.click(await screen.findByRole("button", { name: "Run query" }));
    expect(await screen.findByText(/No data to check/)).toBeTruthy();
    expect(screen.queryByText(/Nothing found/)).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Run query" }));
    expect(await screen.findByText(/Nothing found/)).toBeTruthy();
    expect(screen.getByText(/3 claim/)).toBeTruthy();
    expect(screen.queryByText(/No data to check/)).toBeNull();
  });

  it("shows requirement coverage per section", async () => {
    const section = { id: "d/section/intro", kind: "section", label: "Intro" };
    const getGraphQuery = vi.fn(async () => ({ items: [], noData: false, coverage: { requirement: 2, section: 1 }, sections: [{ section, satisfied: [{ id: "r1", kind: "requirement", label: "metodología" }], missing: [{ id: "r2", kind: "requirement", label: "alcance" }] }] }));
    openReview("/review/graph", makeReviewApi({ getGraphQuery }));
    await screen.findByText("The semantic graph is empty");
    await pick("Query", "Requirement coverage");
    await userEvent.click(screen.getByRole("button", { name: "Run query" }));
    const table = await screen.findByRole("table", { name: "Requirement coverage" });
    expect(within(table).getByText("alcance")).toBeTruthy();
    expect(within(table).getByText("metodología")).toBeTruthy();
  });

  it("filters results by document", async () => {
    const items = [{ id: "a/claim/1", kind: "claim", label: "Claim of A" }, { id: "b/claim/2", kind: "claim", label: "Claim of B" }];
    const getGraphQuery = vi.fn(async () => ({ items, noData: false, coverage: { claim: 2, evidence: 0 } }));
    const node = (id: string) => ({ id, label: id, type: "claim" as const, confidence: 1, x: 1, y: 1 });
    openReview("/review/graph", makeReviewApi({ getGraphQuery, getGraph: async () => ({ nodes: items.map(i => node(i.id)), edges: [] }) }));
    await userEvent.click(await screen.findByRole("button", { name: "Run query" }));
    expect(await screen.findByText("Claim of A")).toBeTruthy();
    await pick("Document", "b");
    expect(screen.queryByText("Claim of A")).toBeNull();
    expect(screen.getByText("Claim of B")).toBeTruthy();
  });

  it("says when the graph overview itself is unavailable", async () => {
    openReview("/review/graph", makeReviewApi({ getGraph: async () => ({ nodes: [], edges: [], unavailable: true, warnings: ["graph unavailable: no store"] }) }));
    expect(await screen.findByText(/graph unavailable: no store/)).toBeTruthy();
    expect(screen.queryByText("The semantic graph is empty")).toBeNull();
  });

  it("reports an unavailable graph read model", async () => {
    openReview("/review/graph", makeReviewApi({ getGraphQuery: async () => ({ items: [], graphUnavailable: true, warnings: ["graph index is stale"] }) }));
    await userEvent.click(await screen.findByRole("button", { name: "Run query" }));
    expect(await screen.findByText(/graph index is stale/)).toBeTruthy();
  });
});

describe("pipeline receipt", () => {
  it("links a finished run to its evidence", async () => {
    const api = makeReviewApi({ getRun: async (id: string) => ({ id, status: "succeeded", created_at: "2026-01-01T00:00:00Z", payload: { document_id: "doc-1" } }) });
    openReview("/pipeline/runs/run-1", api);
    const link = await screen.findByRole("link", { name: "Review evidence for this run" });
    expect(link.getAttribute("href")).toContain("/review/evidence/run-1");
  });
});
