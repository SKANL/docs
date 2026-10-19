// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Suspense, lazy } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiConfigurationError, ApiError } from "../api/errors";
import { ErrorState } from "../components/shared/ErrorState";
import { RouteErrorBoundary } from "../components/shared/RouteErrorBoundary";
import { errorKind, technicalDetails } from "../lib/friendly-error";
import { I18nProvider, translate } from "../lib/i18n";
import { makeReviewApi, openReview } from "./reviewHarness";

afterEach(() => { cleanup(); window.location.hash = ""; localStorage.clear(); });

const raw = "IntegrityError: UNIQUE constraint failed: documents.id";
const api = (status: number, code = "x") => new ApiError(raw, status, code, { field: "id" }, "rq-42");

describe("errorKind", () => {
  it.each([
    [new TypeError("Failed to fetch"), "network"],
    [new TypeError("Failed to fetch dynamically imported module: http://x/assets/a.js"), "unknown"],
    [new TypeError("Importing a module script failed."), "unknown"],
    [new TypeError("error loading dynamically imported module"), "unknown"],
    [new DOMException("Request timed out", "TimeoutError"), "network"],
    [api(0), "network"],
    [api(401), "auth"], [api(403), "auth"],
    [api(404), "notFound"],
    [api(409), "conflict"],
    [api(400), "validation"], [api(422), "validation"],
    [api(500), "server"], [api(503), "server"],
    [api(418), "unknown"],
    [new Error("boom"), "unknown"],
    [new ApiConfigurationError("no base url"), "unknown"],
    ["weird", "unknown"],
  ])("%#", (error, kind) => expect(errorKind(error)).toBe(kind));
});

describe("technicalDetails", () => {
  it("lists message, code, status and request id for an API error", () => {
    expect(technicalDetails(api(409, "doc_exists"))).toEqual([["message", raw], ["code", "doc_exists"], ["status", "409"], ["requestId", "rq-42"]]);
  });
  it("lists only the message for a plain error", () => {
    expect(technicalDetails(new Error("boom"))).toEqual([["message", "boom"]]);
  });
});

describe("messages", () => {
  it.each(["network", "auth", "notFound", "conflict", "validation", "server", "unknown"])("%s exists in Spanish and English", kind => {
    expect(translate("en", `error.${kind}`)).not.toBe(`error.${kind}`);
    expect(translate("es", `error.${kind}`)).not.toBe(translate("en", `error.${kind}`));
  });
});

const withI18n = (ui: React.ReactNode) => render(<I18nProvider>{ui}</I18nProvider>);

describe("ErrorState with an error", () => {
  it("shows a plain message and keeps the server text inside a collapsed disclosure", async () => {
    withI18n(<ErrorState error={api(409, "doc_exists")} />);
    const alert = screen.getByRole("alert");
    const details = alert.querySelector("details")!;
    expect(details.open).toBe(false);
    expect(within(alert).getByText(translate("en", "error.conflict"))).toBeTruthy();
    expect(alert.textContent?.replace(details.textContent ?? "", "")).not.toContain(raw);
    await userEvent.click(within(alert).getByText("Technical details"));
    expect(details.open).toBe(true);
    for (const text of [raw, "doc_exists", "409", "rq-42"]) expect(details.textContent).toContain(text);
  });
  it("maps a network failure to the sidecar message", () => {
    withI18n(<ErrorState error={new TypeError("Failed to fetch")} />);
    expect(screen.getByRole("alert").textContent).toContain(translate("en", "error.network"));
  });
  it("still renders a plain message string", () => {
    withI18n(<ErrorState message="Plain" />);
    expect(screen.getByRole("alert").textContent).toContain("Plain");
    expect(screen.getByRole("alert").querySelector("details")).toBeNull();
  });
});

describe("where errors reach the person", () => {
  it("query failures show the friendly message with technical details", async () => {
    openReview("/review/findings", makeReviewApi({ listFindings: async () => { throw api(500, "boom"); } }));
    const alert = await screen.findByRole("alert", {}, { timeout: 5000 });
    expect(alert.textContent).toContain(translate("en", "error.server"));
    expect(alert.querySelector("details")!.textContent).toContain("rq-42");
  });
  it("the route error boundary maps the failure and keeps the original under details", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const Broken = lazy(() => Promise.reject(new TypeError("Failed to fetch dynamically imported module")));
    withI18n(<RouteErrorBoundary><Suspense fallback={null}><Broken /></Suspense></RouteErrorBoundary>);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain(translate("en", "error.unknown"));
    expect(alert.querySelector("details")!.textContent).toContain("Failed to fetch dynamically imported module");
    expect(screen.getByRole("button", { name: "Reload" })).toBeTruthy();
  });
});

describe("ErrorState props", () => {
  it("takes either an error or a message, never both (checked by the type)", () => {
    // @ts-expect-error `error` and `message` are mutually exclusive
    const both = <ErrorState error={new Error("x")} message="ready-made" />;
    expect(both).toBeTruthy();
  });
});
