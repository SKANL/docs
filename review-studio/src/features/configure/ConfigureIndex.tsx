import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { useT } from "@/lib/i18n";
import { ConfigureLayout, configureSections } from "./ConfigureLayout";

/** `/configure`: the landing page that links to each configuration section. */
export function ConfigureIndex() {
  const { t } = useT();
  return <ConfigureLayout title="cfg.index.title" description="cfg.index.summary">
    <ul aria-label={t("cfg.areas")} className="grid gap-3 sm:grid-cols-2">
      {configureSections.map(([id, label, text]) => <li key={id} className="rounded-lg border bg-card p-4"><Button asChild variant="link" className="h-auto p-0 text-base"><Link to={`/configure/${id}`}>{t(label)}</Link></Button><p className="mt-1 text-sm text-muted-foreground">{t(text)}</p></li>)}
    </ul>
  </ConfigureLayout>;
}
