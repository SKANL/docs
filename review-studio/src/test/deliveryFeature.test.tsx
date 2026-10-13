// @vitest-environment jsdom
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import type { PublicationRecord } from "../api/domains/delivery";
import { deliveryApi, deliveryCatalog, packaged, published, record } from "./deliveryHarness";
import { openPipeline } from "./pipelineHarness";

afterEach(() => { cleanup(); window.location.hash = ""; });

const open = (api: Parameters<typeof openPipeline>[1]) => openPipeline("/delivery", api);
const startPublish = async (destination = "final.html") => {
  await userEvent.click(await screen.findByRole("button", { name: "Publish" }));
  const dialog = await screen.findByRole("dialog", { name: "Publish" });
  await userEvent.type(within(dialog).getByRole("textbox", { name: "Destination" }), destination);
  await userEvent.click(within(dialog).getByRole("button", { name: "Review publish" }));
  return dialog;
};

describe("delivery: publish", () => {
  it("requires an explicit confirmation step that summarises destination and policy before sending", async () => {
    const publishDocument = vi.fn(async () => published);
    const { api } = deliveryApi({ publishDocument });
    open(api);
    const dialog = await startPublish();
    expect(publishDocument).not.toHaveBeenCalled();
    expect(dialog.textContent).toContain("final.html");
    expect(dialog.textContent).toContain("release");
    await userEvent.click(within(dialog).getByRole("button", { name: "Confirm and publish" }));
    await waitFor(() => expect(publishDocument).toHaveBeenCalledWith("doc-1", { destination: "final.html", policy: "release" }));
  });

  it("claims success only after the server answers, then shows the result and the new history row", async () => {
    let resolve!: (value: typeof published) => void;
    const publishDocument = vi.fn(() => new Promise<typeof published>(r => { resolve = r; }));
    let history: PublicationRecord[] = [];
    const { api } = deliveryApi({ publishDocument, listPublicationHistory: async () => history });
    open(api);
    const dialog = await startPublish();
    await userEvent.click(within(dialog).getByRole("button", { name: "Confirm and publish" }));
    expect(screen.queryByRole("status", { name: "Publication result" })).toBeNull();
    history = [record({ id: "pub-1", destination: published.destination })];
    resolve(published);
    const result = await screen.findByRole("status", { name: "Publication result" });
    expect(result.textContent).toContain("Published");
    expect(result.textContent).toContain("font substituted");
    const table = await screen.findByRole("table", { name: "Publication history" });
    await waitFor(() => expect(within(table).getByText(/final\.html/)).toBeTruthy());
  });

  it("renders the server policy denial verbatim and never says published", async () => {
    const message = "release policy requires a verified, non-draft build (digest mismatch)";
    const { api } = deliveryApi({ publishDocument: async () => { throw new ApiError(message, 422, "publish_policy_denied"); } });
    open(api);
    const dialog = await startPublish();
    await userEvent.click(within(dialog).getByRole("button", { name: "Confirm and publish" }));
    expect((await within(dialog).findByRole("alert")).textContent).toContain(message);
    expect(screen.queryByRole("status", { name: "Publication result" })).toBeNull();
  });

  it("shows the destination escape error from the server", async () => {
    const message = "Destination must be a relative path inside output/release";
    const publishDocument = vi.fn(async () => { throw new ApiError(message, 400, "destination_not_permitted"); });
    const { api } = deliveryApi({ publishDocument });
    open(api);
    const dialog = await startPublish("../escape.html");
    await userEvent.click(within(dialog).getByRole("button", { name: "Confirm and publish" }));
    expect((await within(dialog).findByRole("alert")).textContent).toContain(message);
    expect(publishDocument).toHaveBeenCalledWith("doc-1", { destination: "../escape.html", policy: "release" });
  });

  it("retries a failed publish with the same request", async () => {
    const publishDocument = vi.fn().mockRejectedValueOnce(new ApiError("Publish failed: disk busy", 409, "publish_failed")).mockResolvedValueOnce(published);
    const { api } = deliveryApi({ publishDocument });
    open(api);
    const dialog = await startPublish();
    await userEvent.click(within(dialog).getByRole("button", { name: "Confirm and publish" }));
    await within(dialog).findByText(/disk busy/);
    await userEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("status", { name: "Publication result" })).toBeTruthy();
    expect(publishDocument).toHaveBeenCalledTimes(2);
    expect(publishDocument.mock.calls[1]).toEqual(publishDocument.mock.calls[0]);
  });

  it("lets the user choose the policy before confirming", async () => {
    const publishDocument = vi.fn(async () => published);
    const { api } = deliveryApi({ publishDocument });
    open(api);
    await userEvent.click(await screen.findByRole("button", { name: "Publish" }));
    const dialog = await screen.findByRole("dialog", { name: "Publish" });
    await userEvent.type(within(dialog).getByRole("textbox", { name: "Destination" }), "a.html");
    await userEvent.click(within(dialog).getByRole("combobox", { name: "Policy" }));
    await userEvent.click(await screen.findByRole("option", { name: "draft" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Review publish" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Confirm and publish" }));
    await waitFor(() => expect(publishDocument).toHaveBeenCalledWith("doc-1", { destination: "a.html", policy: "draft" }));
  });
});

describe("delivery: package", () => {
  it("packages the document and shows the digest", async () => {
    const packageDocument = vi.fn(async () => packaged);
    const { api } = deliveryApi({ packageDocument });
    open(api);
    await userEvent.click(await screen.findByRole("button", { name: "Package" }));
    const dialog = await screen.findByRole("dialog", { name: "Package" });
    await userEvent.type(within(dialog).getByRole("textbox", { name: "Package name (optional)" }), "handoff");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create package" }));
    await waitFor(() => expect(packageDocument).toHaveBeenCalledWith("doc-1", { name: "handoff" }));
    expect((await within(dialog).findByRole("status", { name: "Package result" })).textContent).toContain(packaged.sha256);
    expect(dialog.textContent).toContain(packaged.destination);
  });

  it("surfaces the honest server refusal when there is no build output", async () => {
    const { api } = deliveryApi({ packageDocument: async () => { throw new ApiError("The document has no build output; build it first", 409, "package_source_unavailable"); } });
    open(api);
    await userEvent.click(await screen.findByRole("button", { name: "Package" }));
    const dialog = await screen.findByRole("dialog", { name: "Package" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Create package" }));
    expect((await within(dialog).findByRole("alert")).textContent).toContain("build it first");
  });
});

describe("delivery: release", () => {
  it("starts a release run and opens its detail, leaving approval to the server", async () => {
    const runDocument = vi.fn(async () => ({ id: "run-rel", status: "queued", document_id: "doc-1", pipeline_id: "document", format: "html", policy: "release", links: { self: "", progress: "", cancel: "" } }));
    const { api } = deliveryApi({ runDocument });
    open(api);
    expect(await screen.findByText(/decided by the server/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Start release run" }));
    await waitFor(() => expect(runDocument).toHaveBeenCalledWith("doc-1", { policy: "release" }));
    expect(await screen.findByRole("heading", { name: "Run run-rel" })).toBeTruthy();
  });
});

describe("delivery: history and gating", () => {
  it("lists publications with truncated digests and an evidence link", async () => {
    const { api } = deliveryApi({ listPublicationHistory: async () => [record({ policy: "strict", warnings: ["w1"] })] });
    open(api);
    const table = await screen.findByRole("table", { name: "Publication history" });
    expect(within(table).getByRole("link", { name: "run-3" }).getAttribute("href")).toContain("/review/evidence/run-3");
    expect(table.textContent).toContain("e".repeat(12) + "…");
    expect(table.textContent).not.toContain("e".repeat(64));
    expect(within(table).getByRole("button", { name: /Copy digest/ })).toBeTruthy();
    expect(table.textContent).toContain("strict");
  });

  it("hides actions whose capability is unavailable", async () => {
    const { api } = deliveryApi({ getCapabilities: async () => deliveryCatalog("document.publish", "document.release") });
    open(api);
    await screen.findByRole("button", { name: "Package" });
    expect(screen.queryByRole("button", { name: "Publish" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Start release run" })).toBeNull();
  });

  it("does not load the publication history when its capability is missing", async () => {
    const listPublicationHistory = vi.fn(async () => []);
    const { api } = deliveryApi({ listPublicationHistory, getCapabilities: async () => deliveryCatalog("publications.list") });
    open(api);
    expect(await screen.findByText("Publication history is not available on this server.")).toBeTruthy();
    expect(listPublicationHistory).not.toHaveBeenCalled();
  });

  it("asks for a document first when none is current", async () => {
    const { api } = deliveryApi({ getCurrentDocument: async () => ({ current_document_id: null, document: null }) });
    open(api);
    expect(await screen.findByRole("heading", { name: "Select a document first" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Publish" })).toBeNull();
  });
});
