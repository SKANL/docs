import { useMutation, useQuery, useQueryClient, type UseMutationResult } from "@tanstack/react-query";
import { ApiError } from "@/api/client";
import { useApi } from "@/app/providers";
import { ErrorState } from "@/components/shared/ErrorState";
import { loadCapabilityActions } from "@/lib/capability-registry";

/** Capability gate: true only when the server catalogue lists the capability as available. */
export function useCapability() {
  const api = useApi();
  const { data } = useQuery({ queryKey: ["capabilities"], queryFn: () => loadCapabilityActions(api) });
  return (id: string) => data?.some(item => item.id === id && item.enabled) ?? false;
}

export type ActiveContext = { workspaceId: string | null; workspaceName: string | null; documentId: string | null; documentTitle: string | null };

/** The selected workspace plus its current document. Never guesses either one. */
export function useActiveContext() {
  const api = useApi();
  return useQuery({
    queryKey: ["authoring", "active-context"],
    queryFn: async (): Promise<ActiveContext> => {
      const workspace = (await api.listWorkspaces?.())?.[0];
      if (!workspace) return { workspaceId: null, workspaceName: null, documentId: null, documentTitle: null };
      const current = await api.getCurrentDocument?.(workspace.id);
      return { workspaceId: workspace.id, workspaceName: workspace.name, documentId: current?.current_document_id ?? null, documentTitle: current?.document?.title ?? null };
    },
  });
}

export const authoringKeys = {
  sections: (doc: string) => ["authoring", doc, "sections"],
  classification: (doc: string) => ["authoring", doc, "classification"],
  context: (doc: string) => ["authoring", doc, "context"],
  assets: (doc: string) => ["authoring", doc, "assets"],
  revisions: () => ["authoring", "revisions"],
};

export function useSections(doc: string) {
  const api = useApi();
  return useQuery({ queryKey: authoringKeys.sections(doc), queryFn: () => api.listDocumentSections!(doc), enabled: !!api.listDocumentSections });
}

export function useClassification(doc: string) {
  const api = useApi();
  return useQuery({
    queryKey: authoringKeys.classification(doc),
    // A 404 classification_unavailable means no queue exists yet; that is "nothing pending", not a failure.
    queryFn: async () => {
      try { return (await api.getDocumentClassification!(doc)).items; }
      catch (error) { if (error instanceof ApiError && error.code === "classification_unavailable") return []; throw error; }
    },
    enabled: !!api.getDocumentClassification,
  });
}

export function useContextStatus(doc: string) {
  const api = useApi();
  return useQuery({ queryKey: authoringKeys.context(doc), queryFn: () => api.getDocumentContext!(doc), enabled: !!api.getDocumentContext });
}

/** Mutation with a success toast and cache invalidation; failures stay on the result for <ActionError>. */
export function useAction<V, R>(fn: (variables: V) => Promise<R>, options: { success: (result: R, variables: V) => string; invalidate?: unknown[][]; onDone?: (result: R, variables: V) => void }) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (result, variables) => {
      const message = options.success(result, variables);
      void import("sonner").then(({ toast }) => toast.success(message)); // sonner stays out of the entry chunk
      options.invalidate?.forEach(queryKey => void queryClient.invalidateQueries({ queryKey }));
      options.onDone?.(result, variables);
    },
  });
}

/** The server message as-is (it already says what went wrong); the caller supplies the headline. */
export const errorText = (error: unknown, _what: string) =>
  error instanceof ApiError ? `${error.message}${error.requestId ? ` Request ID: ${error.requestId}.` : ""}` : error instanceof Error ? error.message : "The API returned an unknown error.";

/** Structured server error with a retry that replays the last variables. */
export function ActionError({ action, what }: { action: UseMutationResult<any, Error, any>; what: string }) {
  if (!action.isError) return null;
  return <ErrorState title={`Could not ${what}`} message={errorText(action.error, what)} onRetry={() => action.mutate(action.variables)} retrying={action.isPending} />;
}

export async function fileToBase64(file: File): Promise<string> {
  const url = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error ?? new Error("Could not read the file"));
    reader.readAsDataURL(file);
  });
  return url.slice(url.indexOf(",") + 1);
}

/** Shown in place of an action whose capability the server does not offer. */
export function Unavailable({ children }: { children: string }) {
  return <p className="text-sm text-muted-foreground">{children}</p>;
}
