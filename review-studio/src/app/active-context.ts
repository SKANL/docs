import { useQuery } from "@tanstack/react-query";
import { useApi } from "@/app/providers";

export type ActiveContext = { workspaceId: string | null; workspaceName: string | null; documentId: string | null; documentTitle: string | null };

/** The selected workspace plus its current document. Never guesses either one. */
export function useActiveContext() {
  const api = useApi();
  return useQuery({
    queryKey: ["active-context"],
    queryFn: async (): Promise<ActiveContext> => {
      const workspace = (await api.listWorkspaces?.())?.[0];
      if (!workspace) return { workspaceId: null, workspaceName: null, documentId: null, documentTitle: null };
      const current = await api.getCurrentDocument?.(workspace.id);
      return { workspaceId: workspace.id, workspaceName: workspace.name, documentId: current?.current_document_id ?? null, documentTitle: current?.document?.title ?? null };
    },
  });
}
