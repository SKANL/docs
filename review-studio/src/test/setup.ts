// Imports are hoisted by ES semantics, so they sit here where they really run: before the polyfills below.
import { configure } from "@testing-library/react";
import { setDefaultLocale } from "../lib/i18n";

// jsdom lacks these browser APIs; sonner (matchMedia) and cmdk (ResizeObserver, scrollIntoView) call them on mount.
if (typeof window !== "undefined") {
  window.matchMedia ??= (query: string) => ({
    matches: false, media: query, onchange: null,
    addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false,
  }) as MediaQueryList;
  globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} };
  Element.prototype.scrollIntoView ??= () => {};
  // Radix Select (pointer-driven popper) probes these on open and on item selection.
  Element.prototype.hasPointerCapture ??= () => false;
  Element.prototype.setPointerCapture ??= () => {};
  Element.prototype.releasePointerCapture ??= () => {};
}

// Existing tests assert English copy; production defaults to Spanish.
setDefaultLocale("en");

// findBy*/waitFor default to 1000ms, shorter than a first lazy-route render under load. Run 2 of verification still flaked at 5s on a 700s loaded run.
configure({ asyncUtilTimeout: 10000 });
