// @vitest-environment jsdom
import { MemoryRouter } from "react-router-dom";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import App from "../App";
import { EmptyState } from "../components/shared/EmptyState";
import { ApiError } from "../api/errors";
import { makeApi, openAuthoring } from "./authoringHarness";
import { deliveryApi } from "./deliveryHarness";
import { openPipeline, page, streamingApi } from "./pipelineHarness";
import { artifact, makeReviewApi, openReview } from "./reviewHarness";

afterEach(() => { cleanup(); window.location.hash = ""; localStorage.clear(); });

/** The empty state whose title is `title`, as the person sees it. */
const emptyState = async (title: string) => within((await screen.findByRole("heading", { name: title })).closest("section")!);

describe("EmptyState", () => {
  it("renders the title, the why and a primary link to the step that fills it", () => {
    render(<MemoryRouter><EmptyState title="Nothing" description="Because." action={{ label: "Go", to: "/pipeline" }} /></MemoryRouter>);
    const state = within(screen.getByRole("status"));
    expect(state.getByRole("heading", { name: "Nothing" })).toBeTruthy();
    expect(state.getByText("Because.")).toBeTruthy();
    expect(state.getByRole("link", { name: "Go" }).getAttribute("href")).toBe("/pipeline");
  });
  it("renders a button when the next step happens on the same page", async () => {
    let clicked = false;
    render(<EmptyState title="Nothing" description="Because." action={{ label: "Do it", onClick: () => { clicked = true; } }} />);
    await userEvent.click(screen.getByRole("button", { name: "Do it" }));
    expect(clicked).toBe(true);
  });
});

describe("every empty state carries a next step", () => {
  const link = async (title: string, href: string) => expect((await (await emptyState(title)).findByRole("link")).getAttribute("href")).toBe(href);

  it.each([
    ["findings", "No findings", () => openReview("/review/findings", makeReviewApi({ listFindings: async () => [] })), "#/pipeline"],
    ["artifacts", "No artifacts", () => openReview("/review/artifacts", makeReviewApi({ listArtifacts: async () => [] })), "#/pipeline"],
    ["compare", "Nothing to compare yet", () => openReview("/review/diff", makeReviewApi({ listArtifacts: async () => [artifact()], diffArtifacts: async () => ({}) as never })), "#/pipeline"],
    ["graph", "The semantic graph is empty", () => openReview("/review/graph", makeReviewApi()), "#/pipeline"],
    ["sections", "No sections yet", () => openAuthoring("sections", makeApi({ listDocumentSections: async () => [] })), "#/authoring/sources"],
    ["revisions", "No revisions yet", () => openAuthoring("revisions", makeApi()), "#/authoring/sections"],
    ["classification", "No classification pending", () => openAuthoring("classification", makeApi({ getClassificationQueue: async () => { throw new ApiError("none", 404, "classification_unavailable"); } })), "#/authoring/sources"],
    ["context", "No context topics", () => openAuthoring("context", makeApi()), "#/configure/templates"],
  ])("%s links to the step that fills it", async (_name, title, open, href) => {
    open();
    await link(title as string, href as string);
  });

  it.each([
    ["assets", "No assets", () => openAuthoring("assets", makeApi({ addAsset: async () => ({}) as never })), /Add an asset/, "asset-file"],
    ["runs", "No runs yet", () => openPipeline("/pipeline", streamingApi({ listRunPage: async () => page([]), runDocument: async () => ({}) as never }).api), /Plan or run/, "run-pipeline"],
    ["publications", "Nothing published yet", () => { window.location.hash = "#/delivery"; render(<App api={deliveryApi().api} />); }, /Publish a document/, "publish-document"],
  ])("%s focuses the control that fills it", async (_name, title, open, label, id) => {
    open();
    const button = (await emptyState(title as string)).getByRole("button", { name: label as RegExp });
    await waitFor(() => expect(document.getElementById(id as string)).toBeTruthy());
    await userEvent.click(button);
    expect(document.activeElement).toBe(document.getElementById(id as string));
  });

  it("documents offers to create one", async () => {
    window.location.hash = "#/configure/workspaces";
    render(<App api={makeApi({ listDocuments: async () => [], listTemplates: async () => [{ id: "t", name: "T" }], createDocument: async () => ({ id: "d", title: "D", template: "t", active: true }), getCurrentDocument: async () => ({ current_document_id: null, document: null }) } as never)} />);
    await userEvent.click((await (await emptyState("No documents yet")).findByRole("button", { name: /Create a document/ })));
    expect(await screen.findByRole("dialog")).toBeTruthy();
  });
});
