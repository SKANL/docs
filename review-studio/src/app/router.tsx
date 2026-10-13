import { HashRouter } from "react-router-dom";
import { AppRoutes } from "./routes";

// HashRouter is required: Tauri serves static files from http://tauri.localhost/, so there is no server-side fallback for history URLs.
export function AppRouter({ pollIntervalMs }: { pollIntervalMs?: number }) {
  return <HashRouter><AppRoutes pollIntervalMs={pollIntervalMs} /></HashRouter>;
}
