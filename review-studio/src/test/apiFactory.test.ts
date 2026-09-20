import { describe, expect, it } from "vitest";
import { ApiConfigurationError, ReviewApiClient } from "../api/client";
import { createReviewApi } from "../api/factory";
import { mockApi } from "../api/mockApi";

describe("createReviewApi", () => {
  it("requires a configured remote API when mock mode is not explicitly enabled", () => {
    expect(() => createReviewApi({ isDevelopment: true, mockEnabled: false })).toThrow(ApiConfigurationError);
  });

  it("allows the mock API only with an explicit development opt-in", () => {
    expect(createReviewApi({ isDevelopment: true, mockEnabled: true })).toBe(mockApi);
    expect(() => createReviewApi({ isDevelopment: false, mockEnabled: true })).toThrow(/development or test/i);
  });

  it("selects the configured remote API in production", () => {
    const api = createReviewApi({ apiBaseUrl: "https://review.example.test/v1", isDevelopment: false, mockEnabled: false });
    expect(api).not.toBe(mockApi);
    expect(api.listRuns).toBeTypeOf("function");
    expect(ReviewApiClient).toBeTypeOf("function");
  });
});
