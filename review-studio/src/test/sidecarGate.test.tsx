// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SidecarGate } from "../app/shell/SidecarGate";
import { I18nProvider } from "../lib/i18n";

type Health = { ready: boolean; state: "starting" | "ready" | "failed"; error: string | null };
const ready: Health = { ready: true, state: "ready", error: null };
const starting: Health = { ready: false, state: "starting", error: null };
const failed: Health = { ready: false, state: "failed", error: "sidecar did not become healthy" };

/** Installs a fake Tauri bridge; `health` is consumed one answer per poll, the last one repeats. */
function installTauri(health: Health[], handlers: Record<string, () => unknown> = {}) {
  const queue = [...health];
  const invoke = vi.fn(async (command: string) => {
    if (command === "sidecar_health") return queue.length > 1 ? queue.shift() : queue[0];
    return handlers[command]?.();
  });
  (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = { invoke };
  return invoke;
}

const renderGate = () => render(<I18nProvider><SidecarGate pollIntervalMs={5}><p>app content</p></SidecarGate></I18nProvider>);

afterEach(() => { cleanup(); localStorage.clear(); delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__; });

describe("SidecarGate", () => {
  it("renders the app untouched outside the desktop shell", () => {
    renderGate();
    expect(screen.getByText("app content")).toBeTruthy();
  });

  it("shows a startup screen while the service boots, then the app", async () => {
    installTauri([starting, starting, ready]);
    renderGate();
    const status = await screen.findByRole("status");
    expect(status.textContent).toContain("Starting Review Studio");
    expect(screen.queryByText("app content")).toBeNull();
    expect(await screen.findByText("app content")).toBeTruthy();
  });

  it("shows a failure screen with Retry and View log once the failure is confirmed", async () => {
    installTauri([failed]);
    renderGate();
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Review Studio could not start");
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "View log" })).toBeTruthy();
    expect(screen.queryByText("app content")).toBeNull();
  });

  it("does not flash the failure screen for a single stale 'failed' answer before start", async () => {
    installTauri([failed, starting, ready]);
    renderGate();
    expect(await screen.findByText("app content")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("Retry restarts the service and returns to the app when it comes up", async () => {
    const invoke = installTauri([failed, failed, ready], { sidecar_restart: () => ready });
    renderGate();
    await userEvent.click(await screen.findByRole("button", { name: "Retry" }));
    expect(invoke).toHaveBeenCalledWith("sidecar_restart");
    expect(await screen.findByText("app content")).toBeTruthy();
  });

  it("Retry that fails again goes back to the failure screen", async () => {
    installTauri([failed], { sidecar_restart: () => { throw "no executable"; } });
    renderGate();
    await userEvent.click(await screen.findByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
  });

  it("View log shows the log text, and says so when the log is empty", async () => {
    let text = "boom: port in use";
    installTauri([failed], { sidecar_log: () => text });
    renderGate();
    await userEvent.click(await screen.findByRole("button", { name: "View log" }));
    expect((await screen.findByLabelText("Service log")).textContent).toContain("boom: port in use");
    text = "";
    await userEvent.click(screen.getByRole("button", { name: "View log" }));
    await waitFor(() => expect(screen.getByLabelText("Service log").textContent).toContain("The log is empty"));
  });

  it("speaks Spanish by default", async () => {
    localStorage.setItem("review-studio.locale", "es");
    installTauri([failed]);
    renderGate();
    expect((await screen.findByRole("alert")).textContent).toContain("Review Studio no pudo iniciar");
    expect(screen.getByRole("button", { name: "Reintentar" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Ver registro" })).toBeTruthy();
  });
});
