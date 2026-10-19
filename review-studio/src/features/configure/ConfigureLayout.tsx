import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { PageHeader } from "@/components/shared/PageHeader";
import { useT } from "@/lib/i18n";
import type { MessageKey } from "@/lib/i18n";
import { cn } from "@/lib/utils";

export const configureSections = [
  ["workspaces", "cfg.workspaces", "cfg.workspaces.text"],
  ["templates", "cfg.templates", "cfg.templates.text"],
  ["diagnostics", "cfg.diagnostics", "cfg.diagnostics.text"],
  ["plugins", "cfg.plugins", "cfg.plugins.text"],
] as const satisfies ReadonlyArray<readonly [string, MessageKey, MessageKey]>;

export function ConfigureLayout({ title, description, children }: { title: MessageKey; description: MessageKey; children: ReactNode }) {
  const { t } = useT();
  return <div className="grid gap-6">
    <PageHeader eyebrow={t("cfg.eyebrow")} title={t(title)} description={t(description)} />
    <nav aria-label={t("cfg.sections")} className="flex flex-wrap gap-1">
      {configureSections.map(([id, label]) => <NavLink key={id} to={`/configure/${id}`} className={({ isActive }) => cn("rounded-md px-3 py-1.5 text-sm font-medium hover:bg-muted", isActive && "bg-muted shadow-[inset_0_-2px_0_var(--primary)]")}>{t(label)}</NavLink>)}
    </nav>
    {children}
  </div>;
}
