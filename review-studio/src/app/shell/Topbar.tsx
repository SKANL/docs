import { Command as CommandIcon } from "lucide-react";
import { ApiStatus, type ApiHealth } from "@/components/ApiStatus";
import { Button } from "@/components/ui/button";

export function Topbar({ health, onOpenCommands }: { health: ApiHealth; onOpenCommands(): void }) {
  return <header className="flex h-16 items-center justify-between border-b bg-card px-4 sm:px-8">
    <span className="flex items-center gap-2.5 text-lg tracking-tight">
      <span aria-hidden="true" className="grid size-8 place-items-center rounded-lg bg-primary font-extrabold text-primary-foreground">R</span>
      <span>Review <b>Studio</b></span>
    </span>
    <div className="flex items-center gap-3">
      <ApiStatus health={health} />
      <Button type="button" variant="outline" size="sm" aria-label="Open command menu" aria-keyshortcuts="Control+K Meta+K" onClick={onOpenCommands}>
        <CommandIcon aria-hidden="true" />K
      </Button>
    </div>
  </header>;
}
