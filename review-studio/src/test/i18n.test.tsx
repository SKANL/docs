// @vitest-environment jsdom
import { act, cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { I18nProvider, setDefaultLocale, translate, useT } from "../lib/i18n";
import { en, es } from "../lib/i18n/messages";

afterEach(() => { cleanup(); localStorage.clear(); setDefaultLocale("en"); vi.restoreAllMocks(); });

describe("translate", () => {
  it("looks a key up per locale", () => {
    expect(translate("en", "nav.home")).toBe("Home");
    expect(translate("es", "nav.home")).toBe("Inicio");
  });
  it("interpolates variables", () => {
    expect(translate("en", "ctx.switchTo", { name: "Notes" })).toContain("Notes");
    expect(translate("es", "ctx.switchTo", { name: "Notes" })).toContain("Notes");
  });
  it("falls back to the key when it is unknown", () => {
    expect(translate("es", "no.such.key")).toBe("no.such.key");
  });
  it("leaves a placeholder alone when it names an inherited Object member", () => {
    const source = { en: { "t.k": "{constructor} / {toString} / {name}" }, es: {} };
    expect(translate("en", "t.k", { name: "x" }, source)).toBe("{constructor} / {toString} / x");
  });
  it("has a Spanish message for every English key", () => {
    expect(Object.keys(en).filter(key => !(key in es))).toEqual([]);
  });
  it("falls back to English when Spanish lacks the key", () => {
    expect(translate("es", "test.englishOnly", undefined, { en: { "test.englishOnly": "only en" }, es: {} })).toBe("only en");
  });
});

function Probe() {
  const { t, locale, setLocale } = useT();
  return <div><span data-testid="out">{t("nav.home")}</span><span data-testid="loc">{locale}</span><button onClick={() => setLocale("en")}>en</button><button onClick={() => setLocale("es")}>es</button></div>;
}

describe("I18nProvider", () => {
  it("defaults to Spanish in production", () => {
    setDefaultLocale("es");
    render(<I18nProvider><Probe /></I18nProvider>);
    expect(screen.getByTestId("out").textContent).toBe("Inicio");
  });
  it("is forced to English by the test setup", () => {
    render(<I18nProvider><Probe /></I18nProvider>);
    expect(screen.getByTestId("loc").textContent).toBe("en");
  });
  it("persists the chosen locale and restores it", async () => {
    const first = render(<I18nProvider><Probe /></I18nProvider>);
    await userEvent.click(screen.getByRole("button", { name: "es" }));
    expect(screen.getByTestId("out").textContent).toBe("Inicio");
    first.unmount();
    render(<I18nProvider><Probe /></I18nProvider>);
    expect(screen.getByTestId("loc").textContent).toBe("es");
  });
  it("still works when storage throws", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("denied"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("denied"); });
    render(<I18nProvider><Probe /></I18nProvider>);
    await act(async () => { await userEvent.click(screen.getByRole("button", { name: "es" })); });
    expect(screen.getByTestId("out").textContent).toBe("Inicio");
  });
});
