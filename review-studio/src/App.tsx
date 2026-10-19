import { useMemo } from "react";
import type { ReviewApi } from "./api/models";
import { createReviewApi } from "./api/factory";
import { AppProviders } from "./app/providers";
import { AppRouter } from "./app/router";
import { SidecarGate } from "./app/shell/SidecarGate";

export default function App({ api: providedApi, pollIntervalMs }: { api?: ReviewApi; pollIntervalMs?: number } = {}) {
  const api = useMemo(() => providedApi ?? createReviewApi(), [providedApi]);
  return <AppProviders api={api}><SidecarGate><AppRouter pollIntervalMs={pollIntervalMs} /></SidecarGate></AppProviders>;
}
