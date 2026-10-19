import { describe, expect, it } from "vitest";
import { reportRows } from "../features/review/inspection";

describe("inspection rows", () => {
  it("flags Advanced-only rows structurally", () => {
    const rows = reportRows({ path: "p", media_type: "m", sha256: "9".repeat(64), size_bytes: 1 });
    expect(rows.filter(row => row.advancedOnly).map(row => row.label)).toEqual(["rv.insp.sha"]);
    expect(rows.filter(row => !row.advancedOnly).map(row => row.label)).toEqual(["rv.insp.path", "rv.insp.media", "rv.insp.size"]);
  });
});
