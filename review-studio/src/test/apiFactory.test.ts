import { describe, expect, it } from "vitest";
import { ApiConfigurationError, ReviewApiClient } from "../api/client";
import { createReviewApi } from "../api/factory";

describe("createReviewApi", () => {
  it("requires a configured remote API", () => {
    expect(() => createReviewApi()).toThrow(ApiConfigurationError);
  });

  it("selects the configured fetch-backed API", () => {
    const api = createReviewApi({ apiBaseUrl: "https://review.example.test/v1", fetch: viFetch() });
    expect(api.listRuns).toBeTypeOf("function");
    expect(ReviewApiClient).toBeTypeOf("function");
  });
});

function viFetch(): typeof globalThis.fetch {
  return async () => new Response(JSON.stringify({ items: [] }), { headers: { "content-type": "application/json" } });
}
