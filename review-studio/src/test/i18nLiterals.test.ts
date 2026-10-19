// @vitest-environment node
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Best-effort guard: user-facing JSX string literals in src/features must go through t().
 * It flags (a) JSX text that starts like a sentence and (b) literal text attributes.
 * ponytail: regex scan, not a parser; multi-line JSX text and template literals are not seen. Upgrade to a TS AST walk if it misses real cases.
 */
const root = join(__dirname, "..", "features");
const ATTRS = "aria-label|title|placeholder|description|confirmLabel|label|what|eyebrow";
const TEXT = /(?<=>)\s*([A-Z][a-z]+(?:[ ,.'’&;a-z-]+)[^<>{}]*)\s*(?=<)/g;
const ATTR = new RegExp(`\\b(?:${ATTRS})="([A-Za-z][^"{}]*)"`, "g");

/** file -> literals that are intentionally not translated (identifiers, brand names, code samples). */
const ALLOW: Record<string, string[]> = {
  "configure/ConfigureIndex.tsx": ["cfg.index.title", "cfg.index.summary"], // message keys passed to ConfigureLayout
  "delivery/PublishDialog.tsx": ["final/report.html"], // example path placeholder
  "tools/DocumentTools.tsx": ["out/report.docx"], // example path placeholder
  "tools/TranslationWorkflow.tsx": ["es"], // language code placeholder
};

const files = (dir: string): string[] => readdirSync(dir).flatMap(name => {
  const path = join(dir, name);
  return statSync(path).isDirectory() ? files(path) : path.endsWith(".tsx") ? [path] : [];
});

describe("untranslated JSX literals", () => {
  it("finds no user-facing string literal in src/features outside the allowlist", () => {
    const found: string[] = [];
    for (const path of files(root)) {
      const name = path.slice(root.length + 1).replace(/\\/g, "/");
      const allowed = ALLOW[name] ?? [];
      const source = readFileSync(path, "utf8");
      for (const re of [TEXT, ATTR]) {
        for (const match of source.matchAll(re)) {
          const literal = match[1]!.trim();
          if (literal && !allowed.includes(literal)) found.push(`${name}: ${literal}`);
        }
      }
    }
    expect(found).toEqual([]);
  });

  it("probe: the scan sees a literal it should flag", () => {
    expect([..."<p>Hello there</p>".matchAll(TEXT)].length).toBe(1);
    expect([..."<X aria-label=\"Open it\" />".matchAll(ATTR)].length).toBe(1);
  });
});
