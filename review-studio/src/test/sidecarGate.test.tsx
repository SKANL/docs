// @vitest-environment jsdom
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
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

const renderGate = (startupTimeoutMs?: number, extra: { restartTimeoutMs?: number; recoveryPollMs?: number } = {}) => render(<I18nProvider><SidecarGate pollIntervalMs={5} startupTimeoutMs={startupTimeoutMs} {...extra}><p>app content</p></SidecarGate></I18nProvider>);
const pause = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

afterEach(() => { vi.useRealTimers(); cleanup(); localStorage.clear(); delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__; });

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

  it("Retry shows the startup screen and ignores stale 'failed' polls until the restart settles, then follows its result", async () => {
    let settle!: (health: Health) => void;
    installTauri([failed], { sidecar_restart: () => new Promise<Health>(resolve => { settle = resolve; }) });
    renderGate();
    await userEvent.click(await screen.findByRole("button", { name: "Retry" }));
    await pause(60); // many stale 'failed' polls land while the restart is pending
    expect(screen.getByRole("status").textContent).toContain("Starting Review Studio");
    expect(screen.queryByRole("alert")).toBeNull();
    settle(failed);
    expect(await screen.findByRole("alert")).toBeTruthy();
  });

  it("Retry uses the restart's ready answer even while polls still read 'failed'", async () => {
    let settle!: (health: Health) => void;
    installTauri([failed], { sidecar_restart: () => new Promise<Health>(resolve => { settle = resolve; }) });
    renderGate();
    await userEvent.click(await screen.findByRole("button", { name: "Retry" }));
    await pause(30);
    settle(ready);
    expect(await screen.findByText("app content")).toBeTruthy();
  });

  it("a restart rejection shows the failure screen with the error", async () => {
    installTauri([failed], { sidecar_restart: () => { throw "no executable"; } });
    renderGate();
    await userEvent.click(await screen.findByRole("button", { name: "Retry" }));
    expect((await screen.findByRole("alert")).textContent).toContain("no executable");
  });

  it("gives up after the startup timeout when the service stays 'starting'", async () => {
    vi.useFakeTimers();
    installTauri([starting]);
    renderGate(1000);
    await vi.advanceTimersByTimeAsync(500);
    expect(screen.queryByRole("alert")).toBeNull();
    await vi.advanceTimersByTimeAsync(600);
    expect(screen.getByRole("alert")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
  });

  it("gives up after the startup timeout when every health call errors", async () => {
    vi.useFakeTimers();
    const invoke = installTauri([starting]);
    invoke.mockRejectedValue("ipc down");
    renderGate(1000);
    await vi.advanceTimersByTimeAsync(1100);
    expect(screen.getByRole("alert")).toBeTruthy();
  });

  it("a restart that never settles gives up after the restart timeout and shows the failure screen", async () => {
    vi.useFakeTimers();
    installTauri([failed], { sidecar_restart: () => new Promise<Health>(() => {}) });
    renderGate(10_000, { restartTimeoutMs: 1000 });
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    await act(async () => { screen.getByRole("button", { name: "Retry" }).click(); });
    await act(async () => { await vi.advanceTimersByTimeAsync(500); });
    expect(screen.getByRole("status")).toBeTruthy();
    await act(async () => { await vi.advanceTimersByTimeAsync(600); });
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("timed out");
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
  });

  it("keeps watching after the startup timeout and recovers when the slow service turns healthy", async () => {
    vi.useFakeTimers();
    const invoke = installTauri([starting]);
    renderGate(1000, { recoveryPollMs: 200 });
    await act(async () => { await vi.advanceTimersByTimeAsync(1100); });
    expect(screen.getByRole("alert")).toBeTruthy();
    invoke.mockImplementation(async (command: string) => (command === "sidecar_health" ? ready : undefined));
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(screen.getByText("app content")).toBeTruthy();
    expect(invoke).not.toHaveBeenCalledWith("sidecar_restart");
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
