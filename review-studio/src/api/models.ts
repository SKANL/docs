import type { AuthoringApi } from "./domains/authoring";
import type { DeliveryApi } from "./domains/delivery";
import type { PipelineApi } from "./domains/pipeline";
import type { ReviewDomainApi } from "./domains/review";
import type { SystemApi } from "./domains/system";
import type { TemplatesApi } from "./domains/templates";
import type { ToolsApi } from "./domains/tools";
import type { WorkspacesApi } from "./domains/workspaces";

// The types components import come straight from the domain that owns them.
export type { Capability, CapabilityCatalog } from "./domains/system";
export type { Artifact, GraphQuery, GraphQueryResult, Status } from "./domains/review";
export type { Template } from "./domains/templates";
export type { DocumentRecord, Workspace, WorkspaceMigration, WorkspaceStatus } from "./domains/workspaces";

/**
 * Everything the UI can call, derived from the domains. Every member is optional because a server may not offer
 * it (the capability catalogue says which), except the read models the review and authoring pages always load.
 */
export type ReviewApi =
  Partial<AuthoringApi & DeliveryApi & PipelineApi & ReviewDomainApi & SystemApi & TemplatesApi & ToolsApi & WorkspacesApi>
  & Pick<AuthoringApi, "listRevisions">
  & Pick<ReviewDomainApi,
    | "listFindings"
    | "listArtifacts"
    | "listBaselines"
    | "getGraph"
    | "getGraphQuery">
  & Pick<TemplatesApi, "listTemplates">;
