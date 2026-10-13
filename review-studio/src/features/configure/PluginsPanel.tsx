import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useApi } from "@/app/providers";
import { EmptyState } from "@/components/shared/EmptyState";
import { QueryBoundary } from "@/components/shared/QueryBoundary";
import { StructureView } from "@/components/shared/StructureView";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Unavailable } from "@/components/shared/Unavailable";
import { useActiveContext } from "@/app/active-context";
import { useCapability } from "@/lib/capability-registry";

const text = (value: unknown) => typeof value === "string" ? value : Array.isArray(value) ? value.join(", ") : "-";

/** Read-only plugin registry. Nothing here runs a plugin. */
export function PluginsPanel() {
  const api = useApi();
  const can = useCapability();
  const listed = !!api.listPlugins && can("plugins.list");
  const workspaceId = useActiveContext().data?.workspaceId ?? null;
  const [selected, setSelected] = useState<string | null>(null);
  const list = useQuery({ queryKey: ["configure", workspaceId, "plugins"], queryFn: () => api.listPlugins!(), enabled: listed });
  const detail = useQuery({ queryKey: ["configure", workspaceId, "plugin", selected], queryFn: () => api.getPlugin!(selected!), enabled: !!selected && !!api.getPlugin });
  return <section aria-label="Plugin registry" className="grid gap-3">
    <h2 className="text-xl font-semibold">Plugins</h2>
    <p className="text-sm text-muted-foreground">Review Studio only lists registered plugins; they are never executed here.</p>
    {!listed ? <Unavailable>The plugin registry is not available on this server.</Unavailable>
      : <QueryBoundary query={list} skeleton="h-16 w-full">{plugins => plugins.length === 0 ? <EmptyState title="No plugins registered" description="Plugins registered for this workspace appear here with their trust level." />
      : <Table aria-label="Plugins">
        <TableHeader><TableRow><TableHead>Plugin</TableHead><TableHead>Version</TableHead><TableHead>Capabilities</TableHead><TableHead>Trust</TableHead><TableHead className="w-28"><span className="sr-only">Details</span></TableHead></TableRow></TableHeader>
        <TableBody>{plugins.map(item => {
          const id = text(item.id ?? item.plugin_id);
          return <TableRow key={id}>
            <TableCell className="font-medium">{id}</TableCell><TableCell>{text(item.version)}</TableCell><TableCell>{text(item.capabilities)}</TableCell><TableCell>{text(item.trust)}</TableCell>
            <TableCell>{api.getPlugin && can("plugins.show") && <Button type="button" variant="ghost" size="sm" aria-label={`Details for ${id}`} onClick={() => setSelected(id)}>Details</Button>}</TableCell>
          </TableRow>;
        })}</TableBody>
      </Table>}</QueryBoundary>}
    {selected && <section aria-label="Plugin detail" className="grid gap-2 rounded-lg border bg-card p-4">
      <h3 className="text-lg font-semibold">{selected}</h3>
      <QueryBoundary query={detail} skeleton="h-16 w-full">{data => <StructureView value={data} />}</QueryBoundary>
    </section>}
  </section>;
}
