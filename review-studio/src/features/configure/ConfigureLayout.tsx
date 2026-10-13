import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { PageHeader } from "@/components/shared/PageHeader";
import { cn } from "@/lib/utils";

export const configureSections = [
  ["workspaces", "Workspaces and documents", "Workspaces, documents, and the current document."],
  ["templates", "Templates", "Installed and built-in templates, creation, and validation."],
  ["diagnostics", "Diagnostics", "Environment checks and issue-code explanations."],
  ["plugins", "Plugins", "The read-only plugin registry."],
] as const;

export function ConfigureLayout({ title, description, children }: { title: string; description: string; children: ReactNode }) {
  return <div className="grid gap-6">
    <PageHeader eyebrow="Configure" title={title} description={description} />
    <nav aria-label="Configure sections" className="flex flex-wrap gap-1">
      {configureSections.map(([id, label]) => <NavLink key={id} to={`/configure/${id}`} className={({ isActive }) => cn("rounded-md px-3 py-1.5 text-sm font-medium hover:bg-muted", isActive && "bg-muted shadow-[inset_0_-2px_0_var(--primary)]")}>{label}</NavLink>)}
    </nav>
    {children}
  </div>;
}
