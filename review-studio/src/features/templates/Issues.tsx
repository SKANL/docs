import { Badge } from "@/components/ui/badge";
import { useT } from "@/lib/i18n";
import type { TemplateIssue } from "@/api/domains/templates";

/** Outcome of a check: a badge plus its issues as messages. Server issue dictionaries are read tolerantly and never dumped. */
export function CheckOutcome({ passed, label, issues }: { passed: boolean; label?: string; issues: TemplateIssue[] }) {
  const { t } = useT();
  return <div className="grid gap-2">
    <div className="flex flex-wrap items-center gap-2">
      <Badge variant={passed ? "secondary" : "destructive"}>{passed ? t("tp.passed") : t("tp.issuesFound")}</Badge>
      {label && <span className="text-sm text-muted-foreground">{label}</span>}
    </div>
    {issues.length > 0 && <ul aria-label={t("tp.issues")} className="grid gap-1 text-sm">
      {issues.map((issue, index) => <li key={index} className="flex flex-wrap gap-x-2">
        {issue.code && <code className="text-xs">{issue.code}</code>}
        {issue.severity && <span className="text-muted-foreground">{issue.severity}</span>}
        <span>{issue.message ?? t("tp.noDescription")}</span>
      </li>)}
    </ul>}
  </div>;
}
