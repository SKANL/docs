// @vitest-environment jsdom
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { makeApi, openAuthoring } from "./authoringHarness";

afterEach(() => { cleanup(); window.location.hash = ""; });

const bodyBox = () => screen.getByRole("textbox", { name: "Section body" }) as HTMLTextAreaElement;

describe("section editor", () => {
  it("edits the selected section through a labelled textarea and saves it", async () => {
    const updateDocumentSection = vi.fn(async () => ({}));
    openAuthoring("sections", makeApi({ updateDocumentSection }));
    const body = await screen.findByRole("textbox", { name: "Section body" });
    expect((body as HTMLTextAreaElement).value).toBe("Intro body");
    expect((screen.getByRole("button", { name: "Save section" }) as HTMLButtonElement).disabled).toBe(true);
    await userEvent.clear(body);
    await userEvent.type(body, "Revised");
    await userEvent.click(screen.getByRole("button", { name: "Save section" }));
    await waitFor(() => expect(updateDocumentSection).toHaveBeenCalledWith("doc-1", "intro", "Revised"));
  });

  it("never retries a failed save against a different section", async () => {
    const updateDocumentSection = vi.fn<(doc: string, id: string, text: string) => Promise<Record<string, unknown>>>(async () => { throw new Error("Server unavailable"); });
    openAuthoring("sections", makeApi({ updateDocumentSection }));
    const body = await screen.findByRole("textbox", { name: "Section body" });
    await userEvent.type(body, " edited");
    await userEvent.click(screen.getByRole("button", { name: "Save section" }));
    await screen.findByText("Could not save the section");
    await userEvent.click(screen.getByRole("button", { name: "summary" }));
    await userEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Discard changes" }));
    await waitFor(() => expect(bodyBox().value).toBe("Summary body"));
    const retry = screen.queryByRole("button", { name: /try again/i });
    if (retry) await userEvent.click(retry);
    expect(updateDocumentSection.mock.calls.every(([, id]) => id === "intro")).toBe(true);
  });

  it("guards unsaved changes when switching sections", async () => {
    openAuthoring("sections", makeApi());
    await userEvent.type(await screen.findByRole("textbox", { name: "Section body" }), " more");
    await userEvent.click(screen.getByRole("button", { name: "summary" }));
    await userEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Cancel" }));
    expect(bodyBox().value).toBe("Intro body more");
    await userEvent.click(screen.getByRole("button", { name: "summary" }));
    await userEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Discard changes" }));
    await waitFor(() => expect(bodyBox().value).toBe("Summary body"));
  });

  it("renders review findings as a list and jumps to the section to fix", async () => {
    const reviewDocument = vi.fn(async () => ({
      document_id: "doc-1", section_id: null, passed: false,
      findings: [{ severity: "high", message: "Claim has no evidence", code: "EVID-001", dimension: "evidence", section: "summary" }],
    }));
    openAuthoring("sections", makeApi({ reviewDocument }));
    await screen.findByRole("textbox", { name: "Section body" });
    await userEvent.click(screen.getByRole("button", { name: "Review document" }));
    const panel = await screen.findByRole("region", { name: "Review findings" });
    const item = within(within(panel).getByRole("list")).getByRole("listitem");
    expect(item.textContent).toContain("high");
    expect(item.textContent).toContain("Claim has no evidence");
    expect(item.textContent).toContain("EVID-001");
    expect(item.textContent).not.toContain("{");
    await userEvent.click(within(item).getByRole("button", { name: "Fix in section summary" }));
    await waitFor(() => expect(bodyBox().value).toBe("Summary body"));
    await waitFor(() => expect(document.activeElement).toBe(bodyBox()));
  });

  it("stamps a section after asking who authored it", async () => {
    const stampSection = vi.fn(async () => ({ document_id: "doc-1", section_id: "intro", path: "sections/intro.md", authored_by: "ana", model: "m1", stamped_at: "now" }));
    openAuthoring("sections", makeApi({ stampSection }));
    await screen.findByRole("textbox", { name: "Section body" });
    await userEvent.click(screen.getByRole("button", { name: "Stamp section" }));
    const dialog = await screen.findByRole("dialog", { name: "Stamp section intro" });
    await userEvent.type(within(dialog).getByLabelText("Stamped by"), "ana");
    await userEvent.type(within(dialog).getByLabelText("Model"), "m1");
    await userEvent.click(within(dialog).getByRole("button", { name: "Stamp" }));
    await waitFor(() => expect(stampSection).toHaveBeenCalledWith("doc-1", "intro", { by: "ana", model: "m1" }));
  });

  it("builds a section and packs context for a target", async () => {
    const buildSection = vi.fn(async () => ({ document_id: "doc-1", section_id: "intro", path: "sections/intro.md", proposal: false }));
    const packContext = vi.fn(async () => ({ document_id: "doc-1", target: "all", paths: ["packs/all.md"] }));
    openAuthoring("sections", makeApi({ buildSection, packContext }));
    await screen.findByRole("textbox", { name: "Section body" });
    await userEvent.click(screen.getByRole("button", { name: "Build section" }));
    await waitFor(() => expect(buildSection).toHaveBeenCalledWith("doc-1", "intro"));
    await userEvent.click(screen.getByRole("button", { name: "Pack context" }));
    const dialog = await screen.findByRole("dialog", { name: "Pack context" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Pack" }));
    await waitFor(() => expect(packContext).toHaveBeenCalledWith("doc-1", "all"));
    expect(await screen.findByText("packs/all.md")).toBeTruthy();
  });
});

describe("revisions", () => {
  it("lists revisions as a timeline and opens one", async () => {
    const getRevision = vi.fn(async () => ({ id: "r1", message: "Initial", files: ["a.md", "b.md"], author: "ana" }));
    openAuthoring("revisions", makeApi({
      listRevisions: async () => [{ id: "r1", message: "Initial", author: "ana", date: "2026-01-01", status: "passed", files: 2 }],
      getRevision,
    }));
    const timeline = await screen.findByRole("list", { name: "Revision timeline" });
    expect(within(timeline).getByText("Initial")).toBeTruthy();
    await userEvent.click(within(timeline).getByRole("button", { name: "View revision r1" }));
    await waitFor(() => expect(getRevision).toHaveBeenCalledWith("r1"));
    expect(await screen.findByText("a.md")).toBeTruthy();
  });

  it("revises a target and shows the produced diff summary", async () => {
    const reviseDocument = vi.fn(async () => ({ target_id: "intro", diff: "-old\n+new", summary: "1 line changed", changed_sections: ["intro"], diff_path: "d.diff" }));
    openAuthoring("revisions", makeApi({ reviseDocument }));
    await userEvent.click(await screen.findByRole("button", { name: "Revise document" }));
    const dialog = await screen.findByRole("dialog", { name: "Revise document" });
    await userEvent.type(within(dialog).getByLabelText("Target"), "intro");
    await userEvent.type(within(dialog).getByLabelText("New body"), "new text");
    await userEvent.click(within(dialog).getByRole("button", { name: "Apply revision" }));
    await waitFor(() => expect(reviseDocument).toHaveBeenCalledWith("doc-1", { target_id: "intro", new_body: "new text" }));
    expect(await within(dialog).findByText("1 line changed")).toBeTruthy();
  });
});
