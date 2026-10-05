import { Fragment, Suspense, lazy, useCallback, useEffect, useRef, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { useApi } from "@/app/providers";
import { useApiHealth } from "@/components/ApiStatus";
import { Skeleton } from "@/components/ui/skeleton";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";
import { UpdateNotice } from "./UpdateNotice";

// The palette (cmdk + dialog) is only needed once someone asks for it, so it stays out of the entry chunk.
const CommandPalette = lazy(() => import("./CommandPalette").then(m => ({ default: m.CommandPalette })));

function RouteSkeleton() {
  return <div className="grid gap-4" role="status" aria-label="Loading page"><Skeleton className="h-8 w-48" /><Skeleton className="h-4 w-96 max-w-full" /><Skeleton className="h-40 w-full" /></div>;
}

export function AppShell({ pollIntervalMs }: { pollIntervalMs?: number }) {
  const api = useApi();
  const health = useApiHealth(api, pollIntervalMs);
  const [commandsOpen, setCommandsOpen] = useState(false);
  const commandsOpenRef = useRef(false);
  commandsOpenRef.current = commandsOpen;
  const paletteLoaded = useRef(false);
  if (commandsOpen) paletteLoaded.current = true; // keep it mounted after the first open so Radix can finish its close and focus return
  const opener = useRef<HTMLElement | null>(null);
  const { pathname } = useLocation();
  const main = useRef<HTMLElement>(null);
  const previousPath = useRef(pathname);

  // Move focus to <main> after in-app navigation, but never steal it on first load.
  useEffect(() => {
    if (previousPath.current !== pathname) { previousPath.current = pathname; main.current?.focus(); }
  }, [pathname]);

  // The palette has no Radix trigger (Ctrl+K opens it from anywhere), so Radix cannot restore focus: do it here.
  const setCommands = useCallback((open: boolean) => {
    if (open) opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    else setTimeout(() => opener.current?.focus(), 0);
    setCommandsOpen(open);
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") { event.preventDefault(); setCommands(!commandsOpenRef.current); }
    };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, [setCommands]);

  return <div className="flex min-h-screen flex-col">
    <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-50 focus:rounded-md focus:bg-card focus:px-4 focus:py-2 focus:shadow-lg"
      onClick={event => { event.preventDefault(); main.current?.focus(); }}>Skip to content</a>
    <Topbar health={health} onOpenCommands={() => setCommands(true)} />
    <UpdateNotice />
    <div className="flex flex-1 flex-col md:flex-row">
      <Sidebar />
      {/* Remount on cold-start recovery so pages refetch once the sidecar is ready. */}
      <main id="main" ref={main} tabIndex={-1} className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 outline-none sm:px-8 md:py-10">
        <Fragment key={health.readyEpoch}><Suspense fallback={<RouteSkeleton />}><Outlet /></Suspense></Fragment>
      </main>
    </div>
    <footer className="border-t bg-card px-4 py-4 text-xs text-muted-foreground sm:px-8">Review Studio foundation</footer>
    {(commandsOpen || paletteLoaded.current) && <Suspense fallback={null}><CommandPalette open={commandsOpen} onOpenChange={setCommands} /></Suspense>}
  </div>;
}
