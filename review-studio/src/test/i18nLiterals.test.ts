// @vitest-environment node
import { describe, expect, it } from "vitest";
import { findJsxLiterals } from "./jsxLiterals";

/**
 * Guard: user-facing string literals in src/features must go through t().
 * A TypeScript AST walk (see jsxLiterals.ts) sees JSX text (single or multi-line), text-bearing attributes, and
 * string/template literals reachable from a JSX expression through ternaries, `&&`/`||`/`??`, `+` and templates.
 */
const sources = import.meta.glob("../features/**/*.tsx", { query: "?raw", import: "default", eager: true }) as Record<string, string>;

/** file -> literals that are intentionally not translated (identifiers, brand names, code samples). */
const ALLOW: Record<string, string[]> = {
  "configure/ConfigureIndex.tsx": ["cfg.index.title", "cfg.index.summary"], // message keys passed to ConfigureLayout
  "delivery/PublishDialog.tsx": ["final/report.html"], // example path placeholder
  "tools/DocumentTools.tsx": ["out/report.docx"], // example path placeholder
  "tools/TranslationWorkflow.tsx": ["es"], // language code placeholder
};

describe("untranslated JSX literals", () => {
  it("finds no user-facing string literal in src/features outside the allowlist", () => {
    const found: string[] = [];
    for (const [path, source] of Object.entries(sources)) {
      const name = path.replace("../features/", "");
      const allowed = ALLOW[name] ?? [];
      for (const literal of findJsxLiterals(name, source)) if (!allowed.includes(literal)) found.push(`${name}: ${literal}`);
    }
    expect(found).toEqual([]);
  });

  it("every allowlist entry is still needed", () => {
    const stale = Object.entries(ALLOW).flatMap(([name, literals]) => {
      const source = Object.entries(sources).find(([path]) => path.endsWith(`/${name}`))?.[1] ?? "";
      const seen = findJsxLiterals(name, source);
      return literals.filter(literal => !seen.includes(literal)).map(literal => `${name}: ${literal}`);
    });
    expect(stale).toEqual([]);
  });
});

describe("probe: the scan flags each shape and ignores translated or non-text content", () => {
  const scan = (jsx: string) => findJsxLiterals("probe.tsx", `const A = () => (${jsx});`);

  it.each([
    ["single-line text", "<p>Hello there</p>", ["Hello there"]],
    ["short single word", "<b>Save</b>", ["Save"]],
    ["multi-line text", "<p>\n  First line\n  second line\n</p>", ["First line second line"]],
    ["text beside an expression", "<p>Saved {n} files</p>", ["Saved", "files"]],
    ["literal attribute", '<X aria-label="Open it" />', ["Open it"]],
    ["string expression attribute", '<X title={"Open it"} />', ["Open it"]],
    ["ternary attribute", '<X placeholder={ok ? "Yes please" : t("k")} />', ["Yes please"]],
    ["template attribute", "<X label={`Delete ${name} now`} />", ["Delete", "now"]],
    ["ternary child", '<p>{ok ? "All good" : t("k")}</p>', ["All good"]],
    ["nested ternary child", '<p>{a ? t("k") : b ? "Other" : null}</p>', ["Other"]],
    ["&& child", '<p>{ok && "Shown when ok"}</p>', ["Shown when ok"]],
    ["|| child", '<p>{name || "Untitled"}</p>', ["Untitled"]],
    ["template child", "<p>{`Total: ${n}`}</p>", ["Total:"]],
    ["concatenated child", '<p>{"Total " + n}</p>', ["Total"]],
    ["literal inside a map", "<ul>{xs.map(x => <li key={x}>Item</li>)}</ul>", ["Item"]],
  ])("flags %s", (_shape, jsx, expected) => {
    expect(scan(jsx)).toEqual(expected);
  });

  it.each([
    ["a translated child", '<p>{t("k")}</p>'],
    ["a translated ternary", '<p>{ok ? t("a") : t("b")}</p>'],
    ["a translated attribute", '<X aria-label={t("k")} />'],
    ["punctuation-only text", "<p>·</p>"],
    ["a punctuation-only fallback", '<p>{x ?? "-"}</p>'],
    ["a punctuation-only template", "<p>{`${a} · ${b}`}</p>"],
    ["a class name", '<p className={ok ? "text-xs" : "text-sm"}>{t("k")}</p>'],
    ["a message key argument", '<p>{t(ok ? "a.b" : "c.d")}</p>'],
    ["a string compared in a condition", '<p>{status !== "succeeded" && t("k")}</p>'],
    ["a string on the left of &&", '<p>{"literal" && t("k")}</p>'],
    ["a non-text attribute", '<X data-kind="Something" />'],
  ])("ignores %s", (_shape, jsx) => {
    expect(scan(jsx)).toEqual([]);
  });
});
