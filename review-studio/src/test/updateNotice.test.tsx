// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const install = vi.fn(async () => {});
vi.mock("@tauri-apps/plugin-updater", () => ({ check: async () => ({ version: "9.9.9", downloadAndInstall: install }) }));
import { UpdateNotice } from "../app/shell/UpdateNotice";

afterEach(() => { cleanup(); delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__; });

describe("UpdateNotice", () => {
  it("renders nothing outside Tauri", async () => {
    const { container } = render(<UpdateNotice />);
    await new Promise(resolve => setTimeout(resolve, 20));
    expect(container.textContent).toBe("");
  });
  it("offers and installs an update inside Tauri", async () => {
    (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {};
    render(<UpdateNotice />);
    expect((await screen.findByRole("status")).textContent).toContain("9.9.9");
    await userEvent.click(screen.getByRole("button", { name: "Install update" }));
    await waitFor(() => expect(install).toHaveBeenCalled());
  });
  it("shows an accessible error with retry when the install fails", async () => {
    (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {};
    install.mockRejectedValueOnce(new Error("signature mismatch"));
    render(<UpdateNotice />);
    await userEvent.click(await screen.findByRole("button", { name: "Install update" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("signature mismatch");
    install.mockResolvedValueOnce(undefined);
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    await waitFor(() => expect(install).toHaveBeenCalledTimes(3));
  });
});
