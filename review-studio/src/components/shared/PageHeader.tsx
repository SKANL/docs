import type { ReactNode } from "react";

type Props = { eyebrow?: string; title: string; description?: string; actions?: ReactNode };

export function PageHeader({ eyebrow, title, description, actions }: Props) {
  return <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
    <div className="min-w-0">
      {eyebrow && <p className="mb-1 text-xs font-semibold tracking-wider text-primary uppercase">{eyebrow}</p>}
      <h1 className="text-3xl font-semibold tracking-tight text-balance">{title}</h1>
      {description && <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted-foreground">{description}</p>}
    </div>
    {actions && <div className="flex shrink-0 flex-wrap gap-2">{actions}</div>}
  </header>;
}
