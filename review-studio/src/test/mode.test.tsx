// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ModeProvider, useMode } from "../app/mode";

afterEach(() => { cleanup(); localStorage.clear(); vi.restoreAllMocks(); });

function Probe() {
  const { mode, advanced, hasChosenMode, setMode, setAdvanced } = useMode();
  return <div>
    <span data-testid="state">{`${mode}|${advanced}|${hasChosenMode}`}</span>
    <button onClick={() => setMode("write")}>write</button>
    <button onClick={() => setMode("supervise")}>supervise</button>
    <button onClick={() => setAdvanced(!advanced)}>advanced</button>
  </div>;
}
const state = () => screen.getByTestId("state").textContent;
const mount = () => render(<ModeProvider><Probe /></ModeProvider>);

describe("mode state", () => {
  it("starts in supervise, not advanced, with no mode chosen yet", () => {
    mount();
    expect(state()).toBe("supervise|false|false");
  });
  it("persists mode and advanced across mounts and marks the mode as chosen", async () => {
    const first = mount();
    await userEvent.click(screen.getByRole("button", { name: "write" }));
    await userEvent.click(screen.getByRole("button", { name: "advanced" }));
    expect(state()).toBe("write|true|true");
    first.unmount();
    mount();
    expect(state()).toBe("write|true|true");
  });
  it("counts choosing supervise explicitly as a choice", async () => {
    mount();
    await userEvent.click(screen.getByRole("button", { name: "supervise" }));
    expect(state()).toBe("supervise|false|true");
  });
  it("ignores unknown stored values", () => {
    localStorage.setItem("review-studio.mode", "bogus");
    localStorage.setItem("review-studio.advanced", "maybe");
    mount();
    expect(state()).toBe("supervise|false|false");
  });
  it("keeps working in memory when storage throws", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("denied"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("denied"); });
    mount();
    expect(state()).toBe("supervise|false|false");
    await userEvent.click(screen.getByRole("button", { name: "write" }));
    expect(state()).toBe("write|false|true");
  });
  it("refuses use outside the provider", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<Probe />)).toThrow(/ModeProvider/);
    spy.mockRestore();
  });
});
