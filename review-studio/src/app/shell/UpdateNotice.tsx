import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { useT } from "@/lib/i18n";

type Update = { version: string; downloadAndInstall(): Promise<void> };

/** Tauri-only updater banner. Renders nothing in a browser or when no update is pending. */
export function UpdateNotice() {
  const { t } = useT();
  const [update, setUpdate] = useState<Update>();
  const [error, setError] = useState<string>();
  const [installing, setInstalling] = useState(false);
  useEffect(() => {
    if (!("__TAURI_INTERNALS__" in window)) return;
    import("@tauri-apps/plugin-updater").then(({ check }) => check()).then(value => { if (value) setUpdate(value as Update); }).catch(reason => setError(String(reason)));
  }, []);
  if (!update) return null;
  const install = async () => {
    setError(undefined);
    setInstalling(true);
    try { await update.downloadAndInstall(); } catch (reason) { setError(String(reason)); setInstalling(false); }
  };
  if (error) return <div role="alert" className="flex flex-wrap items-center gap-3 border-b bg-card px-4 py-2 text-sm text-destructive sm:px-8">
    {t("update.failed", { version: update.version, error })}
    <Button type="button" size="sm" variant="outline" onClick={install}>{t("update.retry")}</Button>
  </div>;
  return <div role="status" aria-live="polite" className="flex flex-wrap items-center gap-3 border-b bg-card px-4 py-2 text-sm sm:px-8">
    {t("update.available", { version: update.version })}
    <Button type="button" size="sm" variant="outline" onClick={install} disabled={installing}>{installing ? t("update.installing") : t("update.install")}</Button>
  </div>;
}
