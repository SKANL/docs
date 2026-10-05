// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import type { ReviewApi } from "../api/models";

afterEach(() => { cleanup(); window.location.hash = ""; });

describe("local service cold start", () => {
  it("keeps polling health and reloads the page once the service becomes ready", async () => {
    window.location.hash = "#workspace";
    const health = vi.fn<NonNullable<ReviewApi["health"]>>()
      .mockRejectedValueOnce(new Error("Failed to fetch"))
      .mockResolvedValue({ ready: true, protocol: "docs-sidecar/v1" });
    const listWorkspaces = vi.fn<NonNullable<ReviewApi["listWorkspaces"]>>()
      .mockRejectedValueOnce(new Error("Failed to fetch"))
      .mockResolvedValue([]);
    render(<App api={{ health, listWorkspaces } as unknown as ReviewApi} pollIntervalMs={10} />);

    await waitFor(() => expect(screen.getByText("Review API ready")).toBeTruthy());
    await waitFor(() => expect(listWorkspaces).toHaveBeenCalledTimes(2));
    expect(health.mock.calls.length).toBeGreaterThanOrEqual(2);
  });
});
