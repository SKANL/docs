import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useApi } from "@/app/providers";
import { EmptyState } from "@/components/shared/EmptyState";
import { ErrorState } from "@/components/shared/ErrorState";
import { PageHeader } from "@/components/shared/PageHeader";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { errorText, useActiveContext, useCapability } from "@/features/authoring/data";
import type { FileTool } from "@/api/domains/tools";
import { BuildDocxCard, DocxInspectionPanel, FileToolCard, ReviewRulesCard } from "./DocumentTools";
import { TranslationWorkflow } from "./TranslationWorkflow";

type Entry = { title: string; capability: string; available: boolean; render(documentId: string): ReactNode };
const fileTools: Array<[FileTool, string, string, boolean]> = [
  ["collect-sources", "Collect sources", "List the document's declared sources into a manifest.", false],
  ["collect-issues", "Collect issues", "Gather issue evidence from the repository.", true],
  ["collect-code-evidence", "Collect code evidence", "Gather code evidence from the repository.", true],
  ["build-rules", "Build rules", "Derive the evidence rules from the collected material.", false],
  ["build-ledger", "Build ledger", "Write the fact ledger for the document.", false],
];

/** Specialist tools live here, not in the authoring flow. Each one is closed until the user opens it. */
export function ToolsRoute() {
  const api = useApi();
  const can = useCapability();
  const active = useActiveContext();
  const header = <PageHeader eyebrow="Specialist" title="Tools" description="Collection, rules, DOCX, and translation tools. Open a tool to see its options." />;
  if (active.isPending) return <div className="grid gap-6">{header}<Skeleton className="h-24 w-full" /></div>;
  if (active.isError) return <div className="grid gap-6">{header}<ErrorState message={errorText(active.error, "workspace")} onRetry={() => void active.refetch()} /></div>;
  const documentId = active.data.documentId;

  const entries: Entry[] = [
    ...fileTools.map(([tool, title, description, repo]): Entry => ({ title, capability: tool, available: !!api.runFileTool, render: id => <FileToolCard key={tool} documentId={id} tool={tool} title={title} description={description} withRepoRoot={repo} /> })),
    { title: "Review rules", capability: "review-rules", available: !!api.reviewRules, render: id => <ReviewRulesCard key="rr" documentId={id} /> },
    { title: "Build DOCX", capability: "build-docx", available: !!api.buildDocx, render: id => <BuildDocxCard key="bd" documentId={id} /> },
    { title: "Format audit DOCX", capability: "format-audit-docx", available: !!api.auditDocxFormat, render: id => <DocxInspectionPanel key="fa" documentId={id} /> },
  ];
  const shown = entries.filter(entry => entry.available && can(entry.capability));
  const translate = can("translate") && !!api.translatePdf;
  const missing = [...entries.filter(entry => !shown.includes(entry)).map(entry => entry.title), ...(translate ? [] : ["Translate PDF"])];

  return <div className="grid gap-6">
    {header}
    {documentId ? <section aria-label="Active context" className="rounded-lg border bg-card px-4 py-3 text-sm"><span className="text-muted-foreground">Document</span> {documentId}{active.data.documentTitle ? ` (${active.data.documentTitle})` : ""}</section>
      : <EmptyState title="Select a document first" description="Most tools act on the current document. Choose or create one to use them."><Button asChild><Link to="/configure/workspaces">Open workspaces and documents</Link></Button></EmptyState>}
    {documentId && <div className="grid gap-3">{shown.map(entry => entry.render(documentId))}</div>}
    {translate && <TranslationWorkflow />}
    {missing.length > 0 && <p className="text-sm text-muted-foreground">Not available on this server: {missing.join(", ")}.</p>}
  </div>;
}
