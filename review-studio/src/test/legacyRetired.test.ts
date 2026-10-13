// @vitest-environment node
import { describe, expect, it } from "vitest";

// Every shipped source (tests excluded) as raw text.
const modules = import.meta.glob(["../**/*.{ts,tsx,css}", "!../test/**"], { query: "?raw", import: "default", eager: true }) as Record<string, string>;
const files = Object.entries(modules).map(([name, text]) => ({ name: name.replace("../", ""), text }));
const hits = (pattern: RegExp) => files.filter(file => pattern.test(file.text)).map(file => file.name);

describe("legacy screens are retired", () => {
  it("has no native prompt/confirm dialogs", () => {
    expect(hits(/\b(window\.)?(prompt|confirm)\(/)).toEqual([]);
  });
  it("has no hand-rolled hash routing", () => {
    expect(hits(/location\.hash\s*=[^=]/)).toEqual([]);
    expect(hits(/hashchange/)).toEqual([]);
  });
  it("has no /legacy route or link", () => {
    expect(hits(/\/legacy\b/)).toEqual([]);
    expect(hits(/legacyScreens/)).toEqual([]);
  });
  it("never renders raw JSON in a <pre>", () => {
    expect(hits(/<pre[^>]*>\s*\{\s*JSON\.stringify/)).toEqual([]);
  });
  it("imports none of the replaced modules", () => {
    expect(hits(/legacy-pages|legacy\.css|SectionEditor/)).toEqual([]);
    for (const gone of ["app/legacy-pages.tsx", "app/styles/legacy.css", "components/SectionEditor.tsx"]) expect(files.map(file => file.name)).not.toContain(gone);
  });
});
