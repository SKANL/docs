import type { Workspace } from "@/api/models";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { useT } from "@/lib/i18n";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

type Props = {
  workspaces: Workspace[];
  selectedId: string;
  busy: boolean;
  canCreate: boolean;
  canSelect: boolean;
  onSelect(id: string): void;
  onCreate(): void;
};

export function WorkspaceSwitcher({ workspaces, selectedId, busy, canCreate, canSelect, onSelect, onCreate }: Props) {
  const { t } = useT();
  return <div className="grid max-w-2xl gap-2">
    <Label htmlFor="workspace-select">{t("ws.active")}</Label>
    <div className="grid gap-2 sm:grid-cols-[minmax(12rem,1fr)_auto]">
      <Select value={selectedId} onValueChange={onSelect} disabled={busy || workspaces.length === 0 || !canSelect}>
        <SelectTrigger id="workspace-select" aria-label={t("ws.active")} className="w-full"><SelectValue placeholder={t("ws.choose")} /></SelectTrigger>
        <SelectContent>{workspaces.map(workspace => <SelectItem key={workspace.id} value={workspace.id}>{workspace.name}</SelectItem>)}</SelectContent>
      </Select>
      <Button type="button" variant="outline" onClick={onCreate} disabled={!canCreate || busy}>{t("ws.create")}</Button>
    </div>
    {!canSelect && workspaces.length > 1 && <p className="text-sm text-muted-foreground" role="status">{t("ws.cannotSelect")}</p>}
  </div>;
}
