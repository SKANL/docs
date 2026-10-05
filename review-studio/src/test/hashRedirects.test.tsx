// @vitest-environment jsdom
import { cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import App from "../App";
import { makeApi } from "./authoringHarness";

afterEach(() => { cleanup(); window.location.hash = ""; });
const map: Array<[string, string]> = [
  ["#overview", "#/"], ["#runs", "#/pipeline"], ["#findings", "#/review/findings"], ["#artifacts", "#/review/artifacts"],
  ["#passport", "#/review/evidence"], ["#graph", "#/review/graph"], ["#baselines", "#/review/baselines"], ["#revisions", "#/authoring/revisions"],
  ["#templates", "#/configure/templates"], ["#plugins", "#/configure/plugins"], ["#publication", "#/delivery"], ["#workspace", "#/configure/workspaces"],
];
describe("old hash URLs", () => {
  it.each(map)("%s maps to %s", async (from, to) => {
    window.location.hash = from;
    render(<App api={makeApi({ getGraph: async () => ({ nodes: [], edges: [] }), listBaselines: async () => [], listTemplates: async () => [], listPublications: async () => [], listPlugins: async () => [] } as never)} />);
    await waitFor(() => expect(window.location.hash).toBe(to));
  });
});
