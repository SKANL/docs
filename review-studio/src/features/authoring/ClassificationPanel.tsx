import { useT } from "@/lib/i18n";
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
  const { t } = useT();
  const api = useApi();
  const path = String(item.relative_path);
  const [role, setRole] = useState<Role>(roles.includes(item.proposed_role as Role) ? item.proposed_role as Role : "evidence");
  const confirm = useAction(
    () => api.confirmClassification!(documentId, { relative_path: path, confirmed_role: role }),
    { success: () => t("cls.confirmedToast", { path, role: t(`cls.role.${role}`) }), invalidate: [authoringKeys.classification(documentId)] },
  );
  return <li className="grid gap-2 rounded-lg border bg-card p-4">
    <div className="flex flex-wrap items-center gap-2"><span className="font-medium">{path}</span>
      <Badge variant="outline">{t("cls.proposed", { role: String(item.proposed_role ?? t("cls.unknown")) })}</Badge>
      {item.confidence !== undefined && <span className="text-sm text-muted-foreground">{t("cls.confidence", { value: String(item.confidence) })}</span>}
      {item.confirmed_role ? <Badge variant="secondary">{t("cls.confirmed", { role: String(item.confirmed_role) })}</Badge> : null}
    </div>
    {!item.confirmed_role && (canConfirm ? <form className="flex flex-wrap items-end gap-2" onSubmit={event => { event.preventDefault(); confirm.mutate(undefined); }}>
      <div className="grid gap-1"><Label htmlFor={`role-${path}`}>{t("cls.roleFor", { path })}</Label>
        <Select value={role} onValueChange={next => setRole(next as Role)}>
          <SelectTrigger id={`role-${path}`} aria-label={t("cls.roleFor", { path })} className="w-40"><SelectValue /></SelectTrigger>
          <SelectContent>{roles.map(value => <SelectItem key={value} value={value}>{t(`cls.role.${value}`)}</SelectItem>)}</SelectContent>
        </Select></div>
      <Button type="submit" disabled={confirm.isPending} aria-label={t("cls.confirmLabel", { path })}>{t("cls.confirm")}</Button>
    </form> : <Unavailable>{t("cls.unavailable")}</Unavailable>)}
    <ActionError action={confirm} what={t("act.confirmRole")} />
  </li>;
}

export function ClassificationPanel({ documentId }: { documentId: string }) {
  const { t } = useT();
  const can = useCapability();
  const queue = useClassification(documentId);
  return <div className="grid gap-4">
    <h2 className="text-xl font-semibold">{t("cls.heading")}</h2>
    <QueryBoundary query={queue}>{items => items.length === 0 ? <EmptyState title={t("cls.none.title")} description={t("cls.none.body")} action={{ label: t("empty.uploadSources"), to: "/authoring/sources" }} />
      : <ul className="grid gap-3" aria-label={t("cls.queue")}>{items.map(item => <QueueRow key={String(item.relative_path)} documentId={documentId} item={item} canConfirm={can("document.classify")} />)}</ul>}</QueryBoundary>
  </div>;
}
