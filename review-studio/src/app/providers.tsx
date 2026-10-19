import { Suspense, createContext, lazy, useContext, useState, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { ModeProvider } from "@/app/mode";
import { TooltipProvider } from "@/components/ui/tooltip";
import { I18nProvider } from "@/lib/i18n";
const Toaster = lazy(() => import("@/components/ui/sonner").then(m => ({ default: m.Toaster })));
import type { ReviewApi } from "@/api/models";

const ApiContext = createContext<ReviewApi | null>(null);

export function useApi(): ReviewApi {
  const api = useContext(ApiContext);
  if (!api) throw new Error("useApi must be used inside AppProviders");
  return api;
}

export function AppProviders({ api, children }: { api: ReviewApi; children: ReactNode }) {
  // One client per mounted app so tests and remounts never share a cache.
  const [queryClient] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } }));
  return <ApiContext.Provider value={api}>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
        <I18nProvider><ModeProvider>
          <TooltipProvider>
            {children}
            <Suspense fallback={null}><Toaster /></Suspense>
          </TooltipProvider>
        </ModeProvider></I18nProvider>
      </ThemeProvider>
    </QueryClientProvider>
  </ApiContext.Provider>;
}
