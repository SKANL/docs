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
import type { DiagnosticStatus } from "@/api/domains/tools";

const statusVariant: Record<DiagnosticStatus, "secondary" | "outline" | "destructive" | "default"> = { ok: "secondary", warn: "outline", error: "destructive", unavailable: "outline" };

function IssueCodeLookup() {
  const api = useApi();
  const [code, setCode] = useState("");
  const explain = useMutation({ mutationFn: (value: string) => api.explainIssueCode!(value) });
  return <section aria-label="Explain an issue code" className="grid gap-3">
    <h2 className="text-xl font-semibold">Explain an issue code</h2>
    <form className="flex flex-wrap items-end gap-2" onSubmit={event => { event.preventDefault(); if (code.trim()) explain.mutate(code.trim()); }}>
      <div className="grid gap-1"><Label htmlFor="issue-code">Issue code</Label><Input id="issue-code" autoComplete="off" placeholder="e.g. QA.001" value={code} onChange={event => setCode(event.target.value)} /></div>
      <Button type="submit" variant="outline" disabled={!code.trim() || explain.isPending}>Explain code</Button>
    </form>
    {explain.isError && <ErrorState title="Could not explain the code" error={explain.error} />}
    {explain.data && <section aria-label="Issue code explanation" className="grid gap-2 rounded-lg border bg-card p-4 text-sm">
      <p className="font-medium"><code>{explain.data.code}</code> <span className="text-muted-foreground">{explain.data.family}{explain.data.family_description ? ` · ${explain.data.family_description}` : ""}</span></p>
      <p><span className="text-muted-foreground">Meaning</span> {explain.data.meaning}</p>
      <p><span className="text-muted-foreground">How to fix</span> {explain.data.fix}</p>
    </section>}
  </section>;
}

/** Environment checks for the current document, plus an issue-code lookup. A degraded capability is explained, never hidden. */
export function DoctorPanel() {
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
    <section aria-label="Diagnostics" className="grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xl font-semibold">Diagnostics</h2>
        <div className="flex items-center gap-2"><Switch id="doctor-strict" checked={strict} onCheckedChange={setStrict} /><Label htmlFor="doctor-strict">Strict</Label></div>
      </div>
      {!can("doctor") || !api.getDiagnostics ? <Unavailable>Diagnostics are not available on this server.</Unavailable>
        : <QueryBoundary query={diagnostics} title="Could not run the diagnostics">{report => <>
          <p className="flex items-center gap-2 text-sm"><Badge variant={report.passed ? "secondary" : "destructive"}>{report.passed ? "Passed" : "Needs attention"}</Badge><span className="text-muted-foreground">Checked for {report.document_id}{report.strict ? " (strict)" : ""}</span></p>
          <Table aria-label="Diagnostic checks">
            <TableHeader><TableRow><TableHead>Check</TableHead><TableHead>Status</TableHead><TableHead>Required</TableHead><TableHead>Version</TableHead><TableHead>Detail</TableHead></TableRow></TableHeader>
            <TableBody>{report.checks.map(check => <TableRow key={check.name}>
              <TableCell className="font-medium">{check.name}</TableCell>
              <TableCell><Badge variant={statusVariant[check.status] ?? "outline"}>{check.status}</Badge></TableCell>
              <TableCell>{check.required ? "yes" : "no"}</TableCell><TableCell>{check.version ?? "-"}</TableCell><TableCell className="break-words">{check.detail}</TableCell>
            </TableRow>)}</TableBody>
          </Table>
          {degraded.length > 0 && <section aria-label="Degraded capabilities" className="grid gap-2 rounded-lg border bg-card p-4">
            <h3 className="text-lg font-semibold">Degraded capabilities</h3>
            <p className="text-sm text-muted-foreground">These features run in a reduced mode. The reason is shown as reported.</p>
            <StructureView value={Object.fromEntries(degraded)} />
          </section>}
        </>}</QueryBoundary>}
    </section>
    {can("explain") && api.explainIssueCode && <IssueCodeLookup />}
  </div>;
}
