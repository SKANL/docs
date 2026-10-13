import { useState } from "react";
import { useApi } from "@/app/providers";
import { EmptyState } from "@/components/shared/EmptyState";
import { QueryBoundary } from "@/components/shared/QueryBoundary";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ActionError, useAction } from "@/lib/actions";
import { Unavailable } from "@/components/shared/Unavailable";
import { useCapability } from "@/lib/capability-registry";
import { authoringKeys, useClassification } from "./data";

type Role = "evidence" | "example" | "normative";
const roles: Role[] = ["evidence", "example", "normative"];

function QueueRow({ documentId, item, canConfirm }: { documentId: string; item: Record<string, unknown>; canConfirm: boolean }) {
  const api = useApi();
  const path = String(item.relative_path);
  const [role, setRole] = useState<Role>(roles.includes(item.proposed_role as Role) ? item.proposed_role as Role : "evidence");
  const confirm = useAction(
    () => api.confirmClassification!(documentId, { relative_path: path, confirmed_role: role }),
    { success: () => `Confirmed ${path} as ${role}.`, invalidate: [authoringKeys.classification(documentId)] },
  );
  return <li className="grid gap-2 rounded-lg border bg-card p-4">
    <div className="flex flex-wrap items-center gap-2"><span className="font-medium">{path}</span>
      <Badge variant="outline">proposed: {String(item.proposed_role ?? "unknown")}</Badge>
      {item.confidence !== undefined && <span className="text-sm text-muted-foreground">confidence {String(item.confidence)}</span>}
      {item.confirmed_role ? <Badge variant="secondary">confirmed: {String(item.confirmed_role)}</Badge> : null}
    </div>
    {!item.confirmed_role && (canConfirm ? <form className="flex flex-wrap items-end gap-2" onSubmit={event => { event.preventDefault(); confirm.mutate(undefined); }}>
      <div className="grid gap-1"><Label htmlFor={`role-${path}`}>Role for {path}</Label>
        <Select value={role} onValueChange={next => setRole(next as Role)}>
          <SelectTrigger id={`role-${path}`} aria-label={`Role for ${path}`} className="w-40"><SelectValue /></SelectTrigger>
          <SelectContent>{roles.map(value => <SelectItem key={value} value={value}>{value}</SelectItem>)}</SelectContent>
        </Select></div>
      <Button type="submit" disabled={confirm.isPending} aria-label={`Confirm role for ${path}`}>Confirm</Button>
    </form> : <Unavailable>Confirming roles is not available on this server.</Unavailable>)}
    <ActionError action={confirm} what="confirm the role" />
  </li>;
}

export function ClassificationPanel({ documentId }: { documentId: string }) {
  const can = useCapability();
  const queue = useClassification(documentId);
  return <div className="grid gap-4">
    <h2 className="text-xl font-semibold">Classification</h2>
    <QueryBoundary query={queue}>{items => items.length === 0 ? <EmptyState title="No classification pending" description="Ingest sources first. Classification appears here when a source needs a confirmed role." />
      : <ul className="grid gap-3" aria-label="Classification queue">{items.map(item => <QueueRow key={String(item.relative_path)} documentId={documentId} item={item} canConfirm={can("document.classify")} />)}</ul>}</QueryBoundary>
  </div>;
}
