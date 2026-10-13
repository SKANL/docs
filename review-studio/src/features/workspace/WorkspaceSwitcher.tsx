import type { Workspace } from "../../api/models";
import { Button } from "../../components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";

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
  return <div className="workspace-switcher-row">
    <label className="field-label" htmlFor="workspace-select">Active workspace</label>
    <div className="workspace-switcher-controls">
      <Select value={selectedId} onValueChange={onSelect} disabled={busy || workspaces.length === 0 || !canSelect}>
        <SelectTrigger id="workspace-select" aria-label="Active workspace"><SelectValue placeholder="Choose a workspace" /></SelectTrigger>
        <SelectContent>{workspaces.map(workspace => <SelectItem key={workspace.id} value={workspace.id}>{workspace.name}</SelectItem>)}</SelectContent>
      </Select>
      <Button type="button" variant="outline" onClick={onCreate} disabled={!canCreate || busy}>Create workspace</Button>
    </div>
    {!canSelect && workspaces.length > 1 && <p className="ws-muted" role="status">Workspace selection is unavailable because this API does not support selecting a workspace.</p>}
  </div>;
}
