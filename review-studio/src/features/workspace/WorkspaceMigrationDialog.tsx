import type { Workspace, WorkspaceMigration } from "../../api/models";
import { Button } from "../../components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "../../components/ui/dialog";

type Props = { workspace: Workspace; open: boolean; pending: boolean; report: WorkspaceMigration | null; error?: string; migratedName?: string; onOpenChange(open: boolean): void; onInspect(): void; onMigrate(): void };

export function WorkspaceMigrationDialog({ workspace, open, pending, report, error, migratedName, onOpenChange, onInspect, onMigrate }: Props) {
  return <Dialog open={open} onOpenChange={onOpenChange}>
    <DialogContent aria-describedby="workspace-migration-description">
      <DialogHeader><DialogTitle>Migrate workspace</DialogTitle><DialogDescription id="workspace-migration-description">Inspect the existing workspace first. Migration publishes a new workspace copy and leaves the source unchanged.</DialogDescription></DialogHeader>
      <p className="ws-muted">Source: <strong>{workspace.name}</strong></p>
      {report && <section className="ws-migration-report" aria-label="Migration inspection">
        <p><span>Detected format</span><strong>{report.detected_format}</strong></p>
        <p><span>Migration readiness</span><strong>{report.ready ? "Ready" : "Not ready"}</strong></p>
        {report.errors.length > 0 && <ul>{report.errors.map(error => <li key={error}>{error}</li>)}</ul>}
      </section>}
      {error && <p className="inline-error" role="alert">{error}</p>}
      {migratedName && <p className="ws-success" role="status">Workspace migrated: {migratedName}</p>}
      {pending && <p className="ws-muted" role="status">This operation cannot be cancelled after it is sent. You may close this dialog; the operation will finish.</p>}
      <DialogFooter>
        <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
        <Button type="button" variant="outline" onClick={onInspect} disabled={pending}>{pending ? "Inspecting…" : "Inspect workspace"}</Button>
        <Button type="button" onClick={onMigrate} disabled={pending || !report?.ready || report.published || Boolean(migratedName)}>{pending ? "Migrating…" : error ? "Try again" : "Migrate workspace"}</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>;
}
