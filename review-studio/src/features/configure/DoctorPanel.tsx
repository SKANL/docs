import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useApi } from "@/app/providers";
import { ErrorState } from "@/components/shared/ErrorState";
import { QueryBoundary } from "@/components/shared/QueryBoundary";
import { StructureView } from "@/components/shared/StructureView";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Unavailable } from "@/components/shared/Unavailable";
import { useActiveContext } from "@/app/active-context";
import { useCapability } from "@/lib/capability-registry";
import { statusKey, useT } from "@/lib/i18n";
import type { DiagnosticStatus } from "@/api/domains/tools";

const statusVariant: Record<DiagnosticStatus, "secondary" | "outline" | "destructive" | "default"> = { ok: "secondary", warn: "outline", error: "destructive", unavailable: "outline" };

function IssueCodeLookup() {
  const { t } = useT();
  const api = useApi();
  const [code, setCode] = useState("");
  const explain = useMutation({ mutationFn: (value: string) => api.explainIssueCode!(value) });
  return <section aria-label={t("dx.explain.heading")} className="grid gap-3">
    <h2 className="text-xl font-semibold">{t("dx.explain.heading")}</h2>
    <form className="flex flex-wrap items-end gap-2" onSubmit={event => { event.preventDefault(); if (code.trim()) explain.mutate(code.trim()); }}>
      <div className="grid gap-1"><Label htmlFor="issue-code">{t("dx.code")}</Label><Input id="issue-code" autoComplete="off" placeholder={t("dx.codePlaceholder")} value={code} onChange={event => setCode(event.target.value)} /></div>
      <Button type="submit" variant="outline" disabled={!code.trim() || explain.isPending}>{t("dx.explainBtn")}</Button>
    </form>
    {explain.isError && <ErrorState title={t("dx.explainFailed")} error={explain.error} />}
    {explain.data && <section aria-label={t("dx.explanation")} className="grid gap-2 rounded-lg border bg-card p-4 text-sm">
      <p className="font-medium"><code>{explain.data.code}</code> <span className="text-muted-foreground">{explain.data.family}{explain.data.family_description ? ` · ${explain.data.family_description}` : ""}</span></p>
      <p><span className="text-muted-foreground">{t("dx.meaning")}</span> {explain.data.meaning}</p>
      <p><span className="text-muted-foreground">{t("dx.fix")}</span> {explain.data.fix}</p>
    </section>}
  </section>;
}

/** Environment checks for the current document, plus an issue-code lookup. A degraded capability is explained, never hidden. */
export function DoctorPanel() {
  const { t } = useT();
  const api = useApi();
  const can = useCapability();
  const active = useActiveContext();
  const [strict, setStrict] = useState(false);
  const workspaceId = active.data?.workspaceId ?? null;
  const documentId = active.data?.documentId ?? undefined;
  const diagnostics = useQuery({
    queryKey: ["configure", workspaceId, "diagnostics", documentId ?? "", strict],
    queryFn: () => api.getDiagnostics!({ documentId, strict }),
    enabled: !active.isPending && can("doctor") && !!api.getDiagnostics, retry: false,
  });
  const degraded = Object.entries(diagnostics.data?.capability_diagnostics ?? {});

  return <div className="grid gap-8">
    <section aria-label={t("dx.heading")} className="grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xl font-semibold">{t("dx.heading")}</h2>
        <div className="flex items-center gap-2"><Switch id="doctor-strict" checked={strict} onCheckedChange={setStrict} /><Label htmlFor="doctor-strict">{t("dx.strict")}</Label></div>
      </div>
      {!can("doctor") || !api.getDiagnostics ? <Unavailable>{t("dx.unavailable")}</Unavailable>
        : <QueryBoundary query={diagnostics} title={t("dx.runFailed")}>{report => <>
          <p className="flex items-center gap-2 text-sm"><Badge variant={report.passed ? "secondary" : "destructive"}>{report.passed ? t("dx.passed") : t("dx.attention")}</Badge><span className="text-muted-foreground">{t(report.strict ? "dx.checkedStrict" : "dx.checked", { document: report.document_id })}</span></p>
          <Table aria-label={t("dx.checks")}>
            <TableHeader><TableRow><TableHead>{t("dx.check")}</TableHead><TableHead>{t("dx.status")}</TableHead><TableHead>{t("dx.required")}</TableHead><TableHead>{t("dx.version")}</TableHead><TableHead>{t("dx.detail")}</TableHead></TableRow></TableHeader>
            <TableBody>{report.checks.map(check => <TableRow key={check.name}>
              <TableCell className="font-medium">{check.name}</TableCell>
              <TableCell><Badge variant={statusVariant[check.status] ?? "outline"}>{statusKey("dx.status", check.status) ? t(statusKey("dx.status", check.status)!) : check.status}</Badge></TableCell>
              <TableCell>{check.required ? t("common.yes") : t("common.no")}</TableCell><TableCell>{check.version ?? "-"}</TableCell><TableCell className="break-words">{check.detail}</TableCell>
            </TableRow>)}</TableBody>
          </Table>
          {degraded.length > 0 && <section aria-label={t("dx.degraded")} className="grid gap-2 rounded-lg border bg-card p-4">
            <h3 className="text-lg font-semibold">{t("dx.degraded")}</h3>
            <p className="text-sm text-muted-foreground">{t("dx.degradedBody")}</p>
            <StructureView value={Object.fromEntries(degraded)} />
          </section>}
        </>}</QueryBoundary>}
    </section>
    {can("explain") && api.explainIssueCode && <IssueCodeLookup />}
  </div>;
}
