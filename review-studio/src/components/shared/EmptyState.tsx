import type { ReactNode } from "react";

type Props = { title: string; description?: string; children?: ReactNode };

export function EmptyState({ title, description, children }: Props) {
  return <section className="rounded-xl border border-dashed bg-card p-8 text-center" role="status">
    <h2 className="text-lg font-semibold">{title}</h2>
    {description && <p className="mx-auto mt-2 max-w-xl text-sm leading-relaxed text-muted-foreground">{description}</p>}
    {children && <div className="mt-4 flex justify-center gap-2">{children}</div>}
  </section>;
}
