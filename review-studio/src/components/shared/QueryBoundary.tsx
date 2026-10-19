import type { ReactNode } from "react";
import { ErrorState } from "@/components/shared/ErrorState";
import { Skeleton } from "@/components/ui/skeleton";

/** What a boundary reads from a react-query result; plain and infinite queries both fit. */
type QueryLike<T> = { isPending: boolean; isError: boolean; error: unknown; data: T | undefined; refetch(): unknown };

type Props<T> = {
  query: QueryLike<T>;
  /** Headline of the error alert, e.g. "Could not load findings". */
  title?: string;
  /** Size of the loading placeholder. */
  skeleton?: string;
  /** Page header kept above the placeholder and the error, so a route never loses its title while loading. */
  header?: ReactNode;
  children: (data: T) => ReactNode;
};

/** The three states every query-backed view shares: a placeholder while loading, a retryable error, then the data. */
export function QueryBoundary<T>({ query, title, skeleton = "h-24 w-full", header, children }: Props<T>) {
  const wrap = (content: ReactNode) => header ? <div className="grid gap-6">{header}{content}</div> : content;
  if (query.isPending) return wrap(<Skeleton className={skeleton} />);
  if (query.isError) return wrap(<ErrorState title={title} error={query.error} onRetry={() => void query.refetch()} />);
  return <>{children(query.data as T)}</>;
}
