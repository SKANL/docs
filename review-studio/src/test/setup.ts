// jsdom lacks these browser APIs; sonner (matchMedia) and cmdk (ResizeObserver, scrollIntoView) call them on mount.
if (typeof window !== "undefined") {
  window.matchMedia ??= (query: string) => ({
    matches: false, media: query, onchange: null,
    addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false,
  }) as MediaQueryList;
  globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} };
  Element.prototype.scrollIntoView ??= () => {};
}
