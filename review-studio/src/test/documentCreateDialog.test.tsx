// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../lib/i18n";
import { DocumentCreateDialog } from "../features/documents/DocumentCreateDialog";
import type { Template } from "../api/models";

afterEach(cleanup);

const template = { id: "report", name: "Report" } as Template;
const dialog = (templates: Template[]) => <I18nProvider><DocumentCreateDialog open pending={false} templates={templates} onOpenChange={() => {}} onSubmit={vi.fn()} /></I18nProvider>;

describe("DocumentCreateDialog", () => {
  it("puts focus on the Document ID field when it opens", async () => {
    render(dialog([template]));
    expect(document.activeElement).toBe(await screen.findByRole("textbox", { name: "Document ID" }));
  });

  it("keeps what was typed when the parent re-renders with a fresh (empty) template list", async () => {
    // The route passes `templates.data ?? []`: a new array on every render until the catalogue loads.
    const view = render(dialog([]));
    await userEvent.type(await screen.findByRole("textbox", { name: "Document ID" }), "kbd");
    view.rerender(dialog([]));
    view.rerender(dialog([]));
    expect((screen.getByRole("textbox", { name: "Document ID" }) as HTMLInputElement).value).toBe("kbd");
  });

  it("preselects the first template once the catalogue arrives, without wiping the fields", async () => {
    const view = render(dialog([]));
    await userEvent.type(await screen.findByRole("textbox", { name: "Document ID" }), "kbd");
    view.rerender(dialog([template]));
    expect((screen.getByRole("textbox", { name: "Document ID" }) as HTMLInputElement).value).toBe("kbd");
    expect(screen.getByRole("combobox", { name: "Template" }).textContent).toBe("Report");
  });
});
