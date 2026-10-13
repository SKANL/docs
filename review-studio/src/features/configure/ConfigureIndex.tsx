import { Link } from "react-router-dom";
import { areas } from "@/app/areas";
import { Button } from "@/components/ui/button";
import { ConfigureLayout, configureSections } from "./ConfigureLayout";

/** `/configure`: the landing page that links to each configuration section. */
export function ConfigureIndex() {
  const area = areas.find(item => item.id === "configure")!;
  return <ConfigureLayout title={area.label} description={area.summary}>
    <ul aria-label="Configure areas" className="grid gap-3 sm:grid-cols-2">
      {configureSections.map(([id, label, text]) => <li key={id} className="rounded-lg border bg-card p-4"><Button asChild variant="link" className="h-auto p-0 text-base"><Link to={`/configure/${id}`}>{label}</Link></Button><p className="mt-1 text-sm text-muted-foreground">{text}</p></li>)}
    </ul>
  </ConfigureLayout>;
}
