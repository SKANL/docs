// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SectionEditor } from "../components/SectionEditor";
import type { ReviewApi } from "../api/models";

const apiFor = (overrides: Partial<ReviewApi> = {}): ReviewApi => ({
  listRuns: async () => [], listFindings: async () => [], listArtifacts: async () => [],
  getPassport: async () => { throw new Error("unused"); }, getGraph: async () => ({ nodes: [], edges: [] }),
  getGraphQuery: async () => ({ items: [] }), listTemplates: async () => [], listBaselines: async () => [],
  listRevisions: async () => [], listPublications: async () => [], ...overrides,
});

afterEach(() => cleanup());

describe("SectionEditor", () => {
  it("loads a section and saves the edited body", async () => {
    const update = vi.fn().mockResolvedValue({});
    render(<SectionEditor api={apiFor({
      listDocumentSections: async () => [{ id: "intro", filename: "intro.md", body: "Original" }],
      updateDocumentSection: update,
    })} documentId="doc-1" />);

    await waitFor(() => expect(screen.getByDisplayValue("Original")).toBeTruthy());
    fireEvent.change(screen.getByLabelText("Section body"), { target: { value: "Revised" } });
    fireEvent.click(screen.getByRole("button", { name: "Save section revision" }));

    await waitFor(() => expect(update).toHaveBeenCalledWith("doc-1", "intro", "Revised"));
    expect(screen.getByText("Section saved with revision provenance.")).toBeTruthy();
  });

  it("surfaces section load failures", async () => {
    render(<SectionEditor api={apiFor({
      listDocumentSections: async () => { throw new Error("Sections unavailable"); },
      updateDocumentSection: vi.fn(),
    })} documentId="doc-1" />);

    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("Sections unavailable"));
  });
});
