// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { ApiError } from "../api/client";
import { mockApi } from "../api/mockApi";

afterEach(() => {
  cleanup();
  window.location.hash = "";
});

describe("semantic graph explorer", () => {
  it("exposes keyboard-friendly domain query controls and deterministic empty results", async () => {
    window.location.hash = "#graph";
    render(<App api={mockApi} />);

    expect(screen.getByRole("combobox", { name: "Query" })).toBeTruthy();
    fireEvent.change(screen.getByRole("combobox", { name: "Query" }), {
      target: { value: "unused_references" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run query" }));

    await waitFor(() => expect(screen.getByText("No matching nodes were returned.")).toBeTruthy());
    expect(screen.getByText(/not attestations/i)).toBeTruthy();
  });

  it("surfaces authenticated API failures instead of rendering demo data", async () => {
    window.location.hash = "#runs";
    const api = { ...mockApi, listRuns: vi.fn().mockRejectedValue(new ApiError("Authentication required", 401, "authentication_required", undefined, "req-auth")) };
    render(<App api={api} />);

    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("Authentication required"));
    expect(screen.getByRole("alert").textContent).toContain("req-auth");
    expect(screen.queryByText("run-2026-09-15-1432")).toBeNull();
  });
});
