import { useMutation, useQueryClient, type UseMutationResult } from "@tanstack/react-query";
import { formatApiError } from "@/api/errors";
import { ErrorState } from "@/components/shared/ErrorState";

type ActionOptions<V, R> = {
  /** The confirmation for a finished action; omit it for an action that needs none. */
  success?: (result: R, variables: V) => string;
  /** Where the confirmation goes; a toast unless the page shows it inline. */
  notify?: (message: string) => void;
  invalidate?: unknown[][];
  onDone?: (result: R, variables: V) => void;
};

/** Mutation with a confirmation and cache invalidation; failures stay on the result for <ActionError>. */
export function useAction<V, R>(fn: (variables: V) => Promise<R>, options: ActionOptions<V, R>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (result, variables) => {
      const message = options.success?.(result, variables);
      if (message && options.notify) options.notify(message);
      else if (message) void import("sonner").then(({ toast }) => toast.success(message)); // sonner stays out of the entry chunk
      options.invalidate?.forEach(queryKey => void queryClient.invalidateQueries({ queryKey }));
      options.onDone?.(result, variables);
    },
  });
}

/** Structured server error with a retry that replays the last variables. */
export function ActionError({ action, what }: { action: UseMutationResult<any, Error, any>; what: string }) {
  if (!action.isError) return null;
  return <ErrorState title={`Could not ${what}`} message={formatApiError(action.error)} onRetry={() => action.mutate(action.variables)} retrying={action.isPending} />;
}
