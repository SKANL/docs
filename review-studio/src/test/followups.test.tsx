// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Suspense, lazy } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/errors";
import { ApiStatus } from "../components/shared/ApiStatus";
import { ConfirmActionDialog } from "../components/shared/ConfirmActionDialog";
import { ErrorState } from "../components/shared/ErrorState";
import { RouteErrorBoundary } from "../components/shared/RouteErrorBoundary";
import { findingLocation, toFindingRow } from "../features/review/data";
import { I18nProvider, translate } from "../lib/i18n";
import { makeReviewApi, openReview } from "./reviewHarness";

afterEach(() => { cleanup(); localStorage.clear(); });

const raw = "IntegrityError: UNIQUE constraint failed";
const conflict = new ApiError(raw, 409, "doc_exists", {}, "rq-9");

describe("error screens work without an I18nProvider", () => {
  it("ErrorState renders its message and technical details", () => {
    render(<ErrorState error={conflict} />);
    expect(screen.getByRole("alert").textContent).toContain(translate("en", "error.conflict"));
    expect(screen.getByRole("alert").textContent).toContain(raw);
  });
  it("RouteErrorBoundary still recovers when the provider itself is what failed", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const Broken = lazy(() => Promise.reject(new Error("Failed to fetch dynamically imported module")));
    render(<RouteErrorBoundary><Suspense fallback={null}><Broken /></Suspense></RouteErrorBoundary>);
    expect((await screen.findByRole("alert")).textContent).toContain("Failed to fetch dynamically imported module");
    expect(screen.getByRole("button", { name: "Reload" })).toBeTruthy();
  });
});

describe("ApiStatus tooltip", () => {
  const show = (health: Parameters<typeof ApiStatus>[0]["health"]) => render(<I18nProvider><ApiStatus health={health} /></I18nProvider>);
  it("keeps the plain reason and the raw message for support", () => {
    show({ state: "unavailable", detail: "", error: new TypeError("Failed to fetch"), readyEpoch: 0 });
    const title = screen.getByRole("status").getAttribute("title")!;
    expect(title).toContain(translate("en", "error.network"));
    expect(title).toContain("Failed to fetch");
  });
  it("renders for a thrown non-Error and for the missing health endpoint", () => {
    show({ state: "unavailable", detail: "", error: undefined, readyEpoch: 0 });
    cleanup();
    show({ state: "unavailable", detail: "", error: "plain string", readyEpoch: 0 });
    expect(screen.getByRole("status").getAttribute("title")).toContain("plain string");
    cleanup();
    show({ state: "unavailable", detail: "", error: new Error("Health endpoint is not available"), readyEpoch: 0 });
    expect(screen.getByRole("status").getAttribute("title")).toContain("Health endpoint is not available");
  });
});

describe("ConfirmActionDialog error", () => {
  const dialog = (error: unknown) => render(<I18nProvider><ConfirmActionDialog open title="Remove" description="Sure?" confirmLabel="Remove" error={error} onOpenChange={() => {}} onConfirm={() => {}} /></I18nProvider>);
  it("turns a raw API error into the friendly message, with the server text only in the details", async () => {
    dialog(conflict);
    const alert = await screen.findByRole("alert");
    const details = alert.querySelector("details")!;
    expect(within(alert).getByText(translate("en", "error.conflict"))).toBeTruthy();
    expect(alert.textContent?.replace(details.textContent ?? "", "")).not.toContain(raw);
    await userEvent.click(within(alert).getByText("Technical details"));
    expect(details.textContent).toContain(raw);
  });
  it.each([[null], [undefined]])("shows no error for %s", error => {
    dialog(error);
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("toFindingRow fallbacks", () => {
  it("leaves message and location empty so each screen words its own fallback", () => {
    const row = toFindingRow({ id: "f1" });
    expect(row).toMatchObject({ id: "f1", severity: "unknown", message: "", location: "" });
    const t = (key: string, vars?: Record<string, string | number>) => translate("en", key, vars);
    expect(findingLocation(row, t)).toBe("-");
    expect(findingLocation({ ...row, section: "intro", page: 3 }, t)).toContain("intro");
    expect(findingLocation({ ...row, location: "server place", section: "intro" }, t)).toBe("server place");
  });
});

describe("findings filter", () => {
  it("matches the severity word the table shows, in the language it is shown", async () => {
    localStorage.setItem("review-studio.locale", "es");
    openReview("/review", makeReviewApi());
    await userEvent.type(await screen.findByLabelText("Filtrar hallazgos"), "alta");
    expect(screen.getAllByText(/Heading is missing/).length).toBeGreaterThan(0);
  });
});

describe("Spanish labels", () => {
  it("tell the two document operations apart", () => {
    expect(translate("es", "rev.reviseDocument")).not.toBe(translate("es", "sec.reviewDocument"));
    expect(translate("es", "rev.reviseDocument")).not.toBe(translate("es", "act.reviseDocument"));
  });
});
