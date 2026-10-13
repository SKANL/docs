import { useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";

/** One specialist tool. Closed by default so the page reads as a list of purposes, not a wall of forms. */
export function ToolCard({ title, description, children }: { title: string; description: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return <section aria-label={title} className="grid gap-3 rounded-lg border bg-card p-4">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0"><h3 className="text-lg font-semibold">{title}</h3><p className="text-sm text-muted-foreground">{description}</p></div>
      <Button type="button" variant="outline" size="sm" aria-expanded={open} aria-label={`Open ${title}`} onClick={() => setOpen(value => !value)}>{open ? "Hide" : "Open"}</Button>
    </div>
    {open && <div className="grid gap-3">{children}</div>}
  </section>;
}

export function StrictSwitch({ id, checked, onChange }: { id: string; checked: boolean; onChange(value: boolean): void }) {
  return <div className="flex items-center gap-2"><Switch id={id} checked={checked} onCheckedChange={onChange} /><Label htmlFor={id}>Strict</Label></div>;
}
