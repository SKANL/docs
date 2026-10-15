import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";

/** The next step: a link when it lives on another page, a button when it happens on this one. */
export type EmptyAction = { label: string; to: string } | { label: string; onClick(): void };

type Props = { title: string; description?: string; action?: EmptyAction; children?: ReactNode };

/** An honest "nothing here": what is missing, why, and the one step that fills it. */
export function EmptyState({ title, description, action, children }: Props) {
  return <section className="rounded-xl border border-dashed bg-card p-8 text-center" role="status">
    <h2 className="text-lg font-semibold">{title}</h2>
    {description && <p className="mx-auto mt-2 max-w-xl text-sm leading-relaxed text-muted-foreground">{description}</p>}
    {(action || children) && <div className="mt-4 flex justify-center gap-2">
      {action && ("to" in action ? <Button asChild><Link to={action.to}>{action.label}</Link></Button> : <Button type="button" onClick={action.onClick}>{action.label}</Button>)}
      {children}
    </div>}
  </section>;
}

/** Moves focus to the control that fills an empty state on the same page. */
export const focusById = (id: string) => () => document.getElementById(id)?.focus();
