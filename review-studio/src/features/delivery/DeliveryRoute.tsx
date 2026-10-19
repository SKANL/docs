import { focusTargets } from "@/lib/focus-targets";
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useApi } from "@/app/providers";
import { EmptyState } from "@/components/shared/EmptyState";
import { PageHeader } from "@/components/shared/PageHeader";
import { QueryBoundary } from "@/components/shared/QueryBoundary";
import { Button } from "@/components/ui/button";
import { useActiveContext, type ActiveContext } from "@/app/active-context";
import { useCapability } from "@/lib/capability-registry";
import { Facts } from "@/components/shared/Facts";
import type { PublicationResult } from "@/api/domains/delivery";
import { CopyDigest } from "./data";
import { PackageDialog } from "./PackageDialog";
import { PublicationHistory } from "./PublicationHistory";
import { PublishDialog } from "./PublishDialog";
import { ReleasePanel } from "./ReleasePanel";

/** Shown only after the server returned a 201 for this publication. */
function PublicationResultPanel({ result }: { result: PublicationResult }) {
  return <section role="status" aria-label="Publication result" className="grid gap-2 rounded-lg border bg-card p-4">
    <p className="font-medium">Published {result.destination}</p>
    <Facts rows={[
      ["Policy", result.policy], ["Format", result.format], ["Manifest", result.manifest],
      ["Artifact digest", <CopyDigest key="a" value={result.artifact_sha256} />], ["Manifest digest", <CopyDigest key="m" value={result.manifest_sha256} />],
      ["Evidence run", result.provenance_run ? <Link key="r" className="underline-offset-4 hover:underline" to={`/review/evidence/${encodeURIComponent(result.provenance_run)}`}>{result.provenance_run}</Link> : undefined],
    ]} />
    {result.warnings.length > 0 && <ul aria-label="Publication warnings" className="list-disc pl-5 text-sm">{result.warnings.map(warning => <li key={warning}>{warning}</li>)}</ul>}
  </section>;
}

function DeliveryView({ header, context }: { header: ReactNode; context: ActiveContext }) {
  const api = useApi();
  const can = useCapability();
  const [dialog, setDialog] = useState<"package" | "publish" | null>(null);
  const [published, setPublished] = useState<PublicationResult | null>(null);
  const { workspaceId, workspaceName, documentId, documentTitle } = context;
  if (!documentId) return <div className="grid gap-6">{header}
    <EmptyState title="Select a document first" description="Delivery acts on the current document. Choose or create one before packaging or publishing.">
      <Button asChild><Link to="/configure/workspaces">Open workspaces and documents</Link></Button>
    </EmptyState></div>;

  return <div className="grid gap-6">
    {header}
    <section aria-label="Active context" className="flex flex-wrap items-center gap-x-6 gap-y-1 rounded-lg border bg-card px-4 py-3 text-sm">
      <span><span className="text-muted-foreground">Workspace</span> {workspaceName}</span>
      <span><span className="text-muted-foreground">Document</span> {documentId}{documentTitle ? ` (${documentTitle})` : ""}</span>
    </section>
    <section aria-label="Deliver" className="flex flex-wrap items-center gap-2">
      {can("document.package") && api.packageDocument && <Button type="button" variant="outline" onClick={() => setDialog("package")}>Package</Button>}
      {can("document.publish") && api.publishDocument && <Button id={focusTargets.publishDocument} type="button" onClick={() => setDialog("publish")}>Publish</Button>}
    </section>
    {published && <PublicationResultPanel result={published} />}
    {can("document.release") && api.runDocument && <ReleasePanel workspaceId={workspaceId} documentId={documentId} />}
    <PublicationHistory workspaceId={workspaceId} />
    <PackageDialog open={dialog === "package"} workspaceId={workspaceId} documentId={documentId} onOpenChange={open => setDialog(open ? "package" : null)} />
    <PublishDialog open={dialog === "publish"} workspaceId={workspaceId} documentId={documentId} onOpenChange={open => setDialog(open ? "publish" : null)} onPublished={setPublished} />
  </div>;
}

export function DeliveryRoute() {
  const active = useActiveContext();
  const header = <PageHeader eyebrow="Task area" title="Delivery" description="Package the build, publish a verified artifact, start a release, and review what was published." />;
  return <QueryBoundary query={active} header={header}>{context => <DeliveryView header={header} context={context} />}</QueryBoundary>;
}
