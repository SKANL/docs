// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import App from "../App";

afterEach(() => {
  cleanup();
  window.location.hash = "";
});

describe("semantic graph explorer", () => {
  it("exposes keyboard-friendly domain query controls and deterministic empty results", async () => {
    window.location.hash = "#graph";
    render(<App />);

    expect(screen.getByRole("combobox", { name: "Query" })).toBeTruthy();
    fireEvent.change(screen.getByRole("combobox", { name: "Query" }), {
      target: { value: "unused_references" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run query" }));

    await waitFor(() => expect(screen.getByText("No matching nodes were returned.")).toBeTruthy());
    expect(screen.getByText(/not attestations/i)).toBeTruthy();
  });
});
