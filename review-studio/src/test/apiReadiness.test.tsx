// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import type { ReviewApi } from "../api/models";

afterEach(() => { cleanup(); window.location.hash = ""; });

describe("local service cold start", () => {
  it("keeps polling health and reloads the page once the service becomes ready", async () => {
    window.location.hash = "#workspace";
    // State-based, not order-based: the page is a lazy chunk, so it may mount before or after the service turns ready.
    let ready = false;
    const health = vi.fn<NonNullable<ReviewApi["health"]>>(async () => {
      if (!ready) { ready = health.mock.calls.length > 1; if (!ready) throw new Error("Failed to fetch"); }
      return { ready: true, protocol: "docs-sidecar/v1" };
    });
    const listWorkspaces = vi.fn<NonNullable<ReviewApi["listWorkspaces"]>>(async () => {
      if (!ready) throw new Error("Failed to fetch");
      return [];
    });
    render(<App api={{ health, listWorkspaces } as unknown as ReviewApi} pollIntervalMs={10} />);

    await waitFor(() => expect(screen.getByText("Review API ready")).toBeTruthy());
    await waitFor(() => expect(listWorkspaces).toHaveBeenCalled(), { timeout: 5000 });
    await waitFor(() => expect(listWorkspaces.mock.results.some(result => result.type === "return")).toBe(true), { timeout: 5000 });
    expect(health.mock.calls.length).toBeGreaterThanOrEqual(2);
  });
});
