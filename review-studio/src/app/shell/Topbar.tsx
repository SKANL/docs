import { Command as CommandIcon } from "lucide-react";
import { ApiStatus, type ApiHealth } from "@/components/shared/ApiStatus";
import { Button } from "@/components/ui/button";
import { ActiveRunsIndicator } from "@/features/pipeline/ActiveRunsIndicator";
import { ContextSwitcher } from "@/features/workspace/ContextSwitcher";
import { useT } from "@/lib/i18n";
import { ShellControls } from "./ShellControls";

export function Topbar({ health, onOpenCommands }: { health: ApiHealth; onOpenCommands(): void }) {
  const { t } = useT();
  return <header className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 border-b bg-card px-4 py-2 sm:px-8">
    <span className="flex items-center gap-2.5 text-lg tracking-tight">
      <span aria-hidden="true" className="grid size-8 place-items-center rounded-lg bg-primary font-extrabold text-primary-foreground">R</span>
      <span>Review <b>Studio</b></span>
    </span>
    <ContextSwitcher />
    <div className="flex flex-wrap items-center gap-3">
      <ShellControls />
      <ActiveRunsIndicator />
      <ApiStatus health={health} />
      <Button type="button" variant="outline" size="sm" aria-label={t("palette.open")} aria-keyshortcuts="Control+K Meta+K" onClick={onOpenCommands}>
        <CommandIcon aria-hidden="true" />K
      </Button>
    </div>
  </header>;
}
