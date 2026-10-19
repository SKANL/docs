// @vitest-environment jsdom
import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { makeReviewApi, openReview } from "./reviewHarness";

afterEach(() => { cleanup(); window.location.hash = ""; localStorage.clear(); });
const tabNames = async () => within(await screen.findByRole("tablist", {}, { timeout: 5000 })).getAllByRole("tab").map(tab => tab.textContent);

describe("Review tabs", () => {
  it("shows Findings, Artifacts and Compare by default", async () => {
    openReview("/review/findings", makeReviewApi());
    expect(await tabNames()).toEqual(["Findings", "Artifacts", "Compare"]);
  });
  it("adds Evidence, Baselines, Quality checks and Graph under Advanced", async () => {
    localStorage.setItem("review-studio.advanced", "true");
    openReview("/review/findings", makeReviewApi());
    expect(await tabNames()).toEqual(["Findings", "Artifacts", "Evidence", "Baselines", "Compare", "Quality checks", "Graph"]);
  });
  it.each(["baselines", "graph", "evidence", "qa"])("still renders a direct link to the hidden %s tab", async tab => {
    openReview(`/review/${tab}`, makeReviewApi());
    const selected = await screen.findByRole("tab", { selected: true });
    expect(selected).toBeTruthy();
    expect(window.location.hash).toBe(`#/review/${tab}`);
    expect(screen.getByRole("tabpanel")).toBeTruthy();
    expect(screen.queryByRole("tab", { name: "Findings", selected: true })).toBeNull();
  });
});
