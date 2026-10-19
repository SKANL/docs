import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useApi } from "@/app/providers";
import { EmptyState } from "@/components/shared/EmptyState";
import { PageHeader } from "@/components/shared/PageHeader";
import { QueryBoundary } from "@/components/shared/QueryBoundary";
import { Button } from "@/components/ui/button";
import { useActiveContext, type ActiveContext } from "@/app/active-context";
import { useCapability } from "@/lib/capability-registry";
import { useT } from "@/lib/i18n";
import type { FileTool } from "@/api/domains/tools";
import { BuildDocxCard, DocxInspectionPanel, FileToolCard, ReviewRulesCard } from "./DocumentTools";
import { TranslationWorkflow } from "./TranslationWorkflow";

type Entry = { title: string; capability: string; available: boolean; render(documentId: string): ReactNode };
const fileTools: Array<[FileTool, boolean]> = [
  ["collect-sources", false],
  ["collect-issues", true],
  ["collect-code-evidence", true],
  ["build-rules", false],
  ["build-ledger", false],
];

function ToolsView({ header, context }: { header: ReactNode; context: ActiveContext }) {
  const { t } = useT();
  const api = useApi();
  const can = useCapability();
  const documentId = context.documentId;

  const entries: Entry[] = [
    ...fileTools.map(([tool, repo]): Entry => { const title = t(`tl.${tool}.title`); return { title, capability: tool, available: !!api.runFileTool, render: id => <FileToolCard key={tool} documentId={id} tool={tool} title={title} description={t(`tl.${tool}.desc`)} withRepoRoot={repo} /> }; }),
    { title: t("tl.rules.title"), capability: "review-rules", available: !!api.reviewRules, render: id => <ReviewRulesCard key="rr" documentId={id} /> },
    { title: t("tl.docx.title"), capability: "build-docx", available: !!api.buildDocx, render: id => <BuildDocxCard key="bd" documentId={id} /> },
    { title: t("tl.audit.title"), capability: "format-audit-docx", available: !!api.auditDocxFormat, render: id => <DocxInspectionPanel key="fa" documentId={id} /> },
  ];
  const shown = entries.filter(entry => entry.available && can(entry.capability));
  const translate = can("translate") && !!api.translatePdf;
  const missing = [...entries.filter(entry => !shown.includes(entry)).map(entry => entry.title), ...(translate ? [] : [t("tl.tr.title")])];

  return <div className="grid gap-6">
    {header}
    {documentId ? <section aria-label={t("au.activeContext")} className="rounded-lg border bg-card px-4 py-3 text-sm"><span className="text-muted-foreground">{t("au.document")}</span> {documentId}{context.documentTitle ? ` (${context.documentTitle})` : ""}</section>
      : <EmptyState title={t("tl.selectDoc.title")} description={t("tl.selectDoc.body")}><Button asChild><Link to="/configure/workspaces">{t("tl.openWorkspaces")}</Link></Button></EmptyState>}
    {documentId && <div className="grid gap-3">{shown.map(entry => entry.render(documentId))}</div>}
    {translate && <TranslationWorkflow />}
    {missing.length > 0 && <p className="text-sm text-muted-foreground">{t("tl.missing", { list: missing.join(", ") })}</p>}
  </div>;
}

/** Specialist tools live here, not in the authoring flow. Each one is closed until the user opens it. */
export function ToolsRoute() {
  const { t } = useT();
  const active = useActiveContext();
  const header = <PageHeader eyebrow={t("tl.eyebrow")} title={t("tl.title")} description={t("tl.description")} />;
  return <QueryBoundary query={active} header={header}>{context => <ToolsView header={header} context={context} />}</QueryBoundary>;
}
