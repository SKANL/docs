import { useQuery } from "@tanstack/react-query";
import { useApi } from "@/app/providers";

/** Everything the workspace page loads sits under `["workspaces"]`, so one invalidation refreshes the whole page. */
export const workspaceKeys = {
  all: ["workspaces"],
  status: (workspaceId: string) => ["workspaces", workspaceId, "status"],
  documents: (workspaceId: string) => ["workspaces", workspaceId, "documents"],
  documentStatus: (workspaceId: string, documentId: string) => ["workspaces", workspaceId, "documents", documentId, "status"],
  templates: (workspaceId: string) => ["workspaces", workspaceId, "templates"],
};

/** Changes that move the selected workspace or its current document also move what every other page shows. */
export const refreshWorkspaceData = [workspaceKeys.all, ["active-context"]];

/** The server lists the selected workspace first. */
export function useWorkspaces() {
  const api = useApi();
  return useQuery({ queryKey: workspaceKeys.all, queryFn: () => api.listWorkspaces!(), enabled: !!api.listWorkspaces });
}

export const sectionClass = "grid gap-4 border-t pt-5";
export const kickerClass = "text-xs font-semibold tracking-wider text-primary uppercase";
