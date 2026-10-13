import { useMemo } from "react";
import type { ReviewApi } from "./api/models";
import { createReviewApi } from "./api/factory";
import { AppProviders } from "./app/providers";
import { AppRouter } from "./app/router";

export default function App({ api: providedApi, pollIntervalMs }: { api?: ReviewApi; pollIntervalMs?: number } = {}) {
  const api = useMemo(() => providedApi ?? createReviewApi(), [providedApi]);
  return <AppProviders api={api}><AppRouter pollIntervalMs={pollIntervalMs} /></AppProviders>;
}
