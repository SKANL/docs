// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import { GlossaryHint } from "../components/shared/GlossaryHint";
import { I18nProvider, setDefaultLocale, translate } from "../lib/i18n";
import { glossaryTerms } from "../lib/i18n/glossary";
import { en, es } from "../lib/i18n/messages";
import { bundle, makeReviewApi, openReview } from "./reviewHarness";

afterEach(() => { cleanup(); localStorage.clear(); window.location.hash = ""; setDefaultLocale("en"); });

describe("one vocabulary", () => {
  it("names running the pipeline and releasing the same way everywhere", () => {
    expect(translate("es", "nav.runs")).toBe("Generar");
    expect(translate("es", "nav.delivery")).toBe("Entregar");
    expect(translate("en", "nav.runs")).toBe("Run");
    expect(translate("en", "nav.delivery")).toBe("Deliver");
    expect(translate("es", "term.run")).toBe("Generar");
    expect(translate("es", "term.deliver")).toBe("Entregar");
  });
});

describe("glossary dictionary", () => {
  it("defines every term in both languages", () => {
    for (const term of glossaryTerms) for (const part of ["name", "body"] as const) {
      const key = `glossary.${term}.${part}`;
      expect(en[key as keyof typeof en], key).toBeTruthy();
      expect(es[key as keyof typeof es], key).toBeTruthy();
    }
  });
});

describe("GlossaryHint", () => {
  const show = () => render(<I18nProvider><GlossaryHint term="finding" /></I18nProvider>);
  it("is a keyboard-operable disclosure that explains the term", async () => {
    show();
    const trigger = screen.getByRole("button", { name: "What is finding?" });
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("note")).toBeNull();
    trigger.focus();
    await userEvent.keyboard("{Enter}");
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    expect(trigger.getAttribute("aria-controls")).toBe(screen.getByRole("note").id);
    expect(screen.getByRole("note").textContent).toMatch(/problem/i);
  });
  it("closes on Escape and returns to the trigger", async () => {
    show();
    const trigger = screen.getByRole("button", { name: "What is finding?" });
    await userEvent.click(trigger);
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("note")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });
  it("speaks Spanish when that is the locale", () => {
    setDefaultLocale("es");
    show();
    expect(screen.getByRole("button", { name: "¿Qué es hallazgo?" })).toBeTruthy();
  });
});

describe("jargon only under Advanced", () => {
  it("hides passports, attestations and digests from the evidence view by default", async () => {
    openReview("/review/evidence/run-1", makeReviewApi({ getRunEvidence: async () => bundle() }));
    await screen.findByRole("heading", { name: "Evidence for run-1" });
    expect(screen.getByRole("link", { name: "a-1" })).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Passport summary" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Evidence digest" })).toBeNull();
    expect(document.body.textContent).not.toMatch(/passport|attestation|digest|sha-256/i);
  });
  it("shows them, with an explanation, once Advanced is on", async () => {
    localStorage.setItem("review-studio.advanced", "true");
    openReview("/review/evidence/run-1", makeReviewApi({ getRunEvidence: async () => bundle() }));
    expect(await screen.findByRole("region", { name: "Passport summary" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Evidence digest" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "What is passport?" })).toBeTruthy();
  });
  it("hides an artifact checksum by default", async () => {
    openReview("/review/artifacts/a-1", makeReviewApi());
    await screen.findByRole("region", { name: "Artifact detail" });
    expect(screen.queryByText("Checksum")).toBeNull();
  });
});
