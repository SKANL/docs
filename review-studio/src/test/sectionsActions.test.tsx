// @vitest-environment jsdom
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { makeApi, openAuthoring } from "./authoringHarness";
import { toolsApi } from "./toolsHarness";
import { deliveryApi } from "./deliveryHarness";
import { openPipeline, streamingApi } from "./pipelineHarness";

afterEach(() => { cleanup(); window.location.hash = ""; localStorage.clear(); });
const body = () => screen.findByRole("textbox", { name: "Section body" }) as Promise<HTMLTextAreaElement>;
const fn = async () => ({}) as never;
const sectionsApi = (over: Record<string, unknown> = {}) => makeApi({ buildSection: fn, reviewSection: fn, reviewDocument: fn, stampSection: fn, packContext: fn, ...over } as never);
const technical = ["Build section", "Stamp section"];

describe("Sections actions", () => {
  it("keeps edit, save and review in front and tucks technical actions away by default", async () => {
    localStorage.setItem("review-studio.mode", "write");
    openAuthoring("sections", sectionsApi());
    await body();
    for (const name of ["Save section", "Review section", "Review document"]) expect(screen.getByRole("button", { name })).toBeTruthy();
    for (const name of [...technical, "Pack context"]) expect(screen.queryByRole("button", { name })).toBeNull();
  });
  it("shows build, stamp and pack context under Advanced", async () => {
    localStorage.setItem("review-studio.mode", "write");
    localStorage.setItem("review-studio.advanced", "true");
    openAuthoring("sections", sectionsApi());
    await body();
    for (const name of [...technical, "Pack context"]) expect(screen.getByRole("button", { name })).toBeTruthy();
  });
  it("leans on review in Supervise: read-only until the person chooses to edit", async () => {
    localStorage.setItem("review-studio.mode", "supervise");
    const updateDocumentSection = vi.fn(async () => ({}));
    openAuthoring("sections", sectionsApi({ updateDocumentSection }));
    expect((await body()).readOnly).toBe(true);
    expect(screen.getByRole("button", { name: "Review section" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Save section" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Edit section" }));
    expect((await body()).readOnly).toBe(false);
    await userEvent.type(await body(), "!");
    await userEvent.click(screen.getByRole("button", { name: "Save section" }));
    await waitFor(() => expect(updateDocumentSection).toHaveBeenCalledWith("doc-1", "intro", "Intro body!"));
  });
  it("puts editing front and centre in Write", async () => {
    localStorage.setItem("review-studio.mode", "write");
    openAuthoring("sections", sectionsApi());
    expect((await body()).readOnly).toBe(false);
    expect(screen.queryByRole("button", { name: "Edit section" })).toBeNull();
  });
});

describe("Sources has one upload form", () => {
  it("offers a single file input, and the no-conversion import only under Advanced", async () => {
    openAuthoring("sources", toolsApi({ ingestSources: fn, importSourceFile: fn }));
    await screen.findByLabelText("Source files");
    expect(screen.getAllByLabelText(/source files?$/i)).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Import without converting" })).toBeNull();
    cleanup();
    localStorage.setItem("review-studio.advanced", "true");
    openAuthoring("sources", toolsApi({ ingestSources: fn, importSourceFile: fn }));
    await screen.findByLabelText("Source files");
    expect(screen.getAllByLabelText(/source files?$/i)).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Import without converting" })).toBeTruthy();
  });
});

describe("one release entry point", () => {
  it("offers Deliver as the primary entry and keeps the raw release run under Advanced", async () => {
    const { api } = deliveryApi({ runDocument: async () => ({ id: "r" }) as never });
    openPipeline("/delivery", api);
    await screen.findByRole("button", { name: "Deliver" });
    expect(screen.queryByRole("button", { name: "Start release run" })).toBeNull();
    cleanup();
    localStorage.setItem("review-studio.advanced", "true");
    openPipeline("/delivery", deliveryApi({ runDocument: async () => ({ id: "r" }) as never }).api);
    expect(await screen.findByRole("button", { name: "Start release run" })).toBeTruthy();
  });
  it("links the pipeline launcher to Deliver and offers the release policy only under Advanced", async () => {
    openPipeline("/pipeline", streamingApi().api);
    const launcher = within(await screen.findByRole("region", { name: "Launch" }));
    const link = launcher.getByRole("link", { name: /Deliver/ });
    expect(link.getAttribute("href")).toBe("#/delivery");
    await userEvent.click(screen.getByRole("combobox", { name: "Policy" }));
    expect(await screen.findByRole("option", { name: "strict" })).toBeTruthy();
    expect(screen.queryByRole("option", { name: "release" })).toBeNull();
  });
});
