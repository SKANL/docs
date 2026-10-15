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
import { setDefaultLocale } from "../lib/i18n";
setDefaultLocale("en");
