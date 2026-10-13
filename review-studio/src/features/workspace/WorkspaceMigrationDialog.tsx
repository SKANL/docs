import type { Workspace, WorkspaceMigration } from "@/api/models";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";

type Props = { workspace: Workspace; open: boolean; pending: boolean; report: WorkspaceMigration | null; error?: string; migratedName?: string; onOpenChange(open: boolean): void; onInspect(): void; onMigrate(): void };

export function WorkspaceMigrationDialog({ workspace, open, pending, report, error, migratedName, onOpenChange, onInspect, onMigrate }: Props) {
  return <Dialog open={open} onOpenChange={onOpenChange}>
    <DialogContent showCloseButton={false} aria-describedby="workspace-migration-description" className="max-h-[85vh] overflow-y-auto">
      <DialogHeader><DialogTitle>Migrate workspace</DialogTitle><DialogDescription id="workspace-migration-description">Inspect the existing workspace first. Migration publishes a new workspace copy and leaves the source unchanged.</DialogDescription></DialogHeader>
      <p className="text-sm text-muted-foreground">Source: <strong className="text-foreground">{workspace.name}</strong></p>
      {report && <section className="grid gap-2 rounded-md bg-muted p-3 text-sm" aria-label="Migration inspection">
        <p className="flex justify-between gap-4"><span className="text-muted-foreground">Detected format</span><strong>{report.detected_format}</strong></p>
        <p className="flex justify-between gap-4"><span className="text-muted-foreground">Migration readiness</span><strong>{report.ready ? "Ready" : "Not ready"}</strong></p>
        {report.errors.length > 0 && <ul className="list-disc pl-5 text-destructive">{report.errors.map(error => <li key={error}>{error}</li>)}</ul>}
      </section>}
      {error && <p className="text-sm text-destructive" role="alert">{error}</p>}
      {migratedName && <p className="rounded-md bg-success/10 p-3 text-sm text-success" role="status">Workspace migrated: {migratedName}</p>}
      {pending && <p className="text-sm text-muted-foreground" role="status">This operation cannot be cancelled after it is sent. You may close this dialog; the operation will finish.</p>}
      <DialogFooter>
        <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
        <Button type="button" variant="outline" onClick={onInspect} disabled={pending}>{pending ? "Inspecting…" : "Inspect workspace"}</Button>
        <Button type="button" onClick={onMigrate} disabled={pending || !report?.ready || report.published || Boolean(migratedName)}>{pending ? "Migrating…" : error ? "Try again" : "Migrate workspace"}</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>;
}
