// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { Suspense, lazy } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RouteErrorBoundary } from "@/components/shared/RouteErrorBoundary";
import { I18nProvider } from "@/lib/i18n";

afterEach(cleanup);

describe("route error boundary", () => {
  it("shows a recoverable error instead of a blank page when a route chunk fails to load", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const Broken = lazy(() => Promise.reject(new Error("Failed to fetch dynamically imported module")));
    render(<I18nProvider><RouteErrorBoundary><Suspense fallback={null}><Broken /></Suspense></RouteErrorBoundary></I18nProvider>);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Could not load this page");
    expect(alert.textContent).toContain("Failed to fetch dynamically imported module");
    expect(screen.getByRole("button", { name: "Reload" })).toBeTruthy();
  });
});
