import { describe, expect, it } from "vitest";
import { mockApi } from "../api/mockApi";

describe("mock review API", () => {
  it("returns deterministic runs and findings", async () => {
    const runs = await mockApi.listRuns();
    const findings = await mockApi.listFindings();
    expect(runs[0].id).toBe("run-2026-09-15-1432");
    expect(findings.filter((finding) => finding.status === "failed")).toHaveLength(2);
  });
});
