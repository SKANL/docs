import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";

type Update = { version: string; downloadAndInstall(): Promise<void> };

/** Tauri-only updater banner. Renders nothing in a browser or when no update is pending. */
export function UpdateNotice() {
  const [update, setUpdate] = useState<Update>();
  const [error, setError] = useState<string>();
  const [installing, setInstalling] = useState(false);
  useEffect(() => {
    if (!("__TAURI_INTERNALS__" in window)) return;
    import("@tauri-apps/plugin-updater").then(({ check }) => check()).then(value => { if (value) setUpdate(value as Update); }).catch(reason => setError(String(reason)));
  }, []);
  if (error || !update) return null;
  const install = async () => {
    setInstalling(true);
    try { await update.downloadAndInstall(); } catch (reason) { setError(String(reason)); setInstalling(false); }
  };
  return <div role="status" aria-live="polite" className="flex flex-wrap items-center gap-3 border-b bg-card px-4 py-2 text-sm sm:px-8">
    Update {update.version} is available.
    <Button type="button" size="sm" variant="outline" onClick={install} disabled={installing}>{installing ? "Installing…" : "Install update"}</Button>
  </div>;
}
