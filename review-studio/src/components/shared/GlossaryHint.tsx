import { CircleHelp } from "lucide-react";
import { useId, useRef, useState } from "react";
import type { GlossaryTerm } from "@/lib/i18n/glossary";
import { useT, type MessageKey } from "@/lib/i18n";

/** A small "what is this?" disclosure next to a concept. Keyboard operable; Escape closes it and returns focus to the trigger. */
export function GlossaryHint({ term }: { term: GlossaryTerm }) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const id = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  return <span className="relative inline-flex align-middle" onKeyDown={event => { if (event.key === "Escape" && open) { setOpen(false); trigger.current?.focus(); } }}>
    <button ref={trigger} type="button" aria-expanded={open} aria-controls={open ? id : undefined} aria-label={t("glossary.whatIs", { term: t(`glossary.${term}.name` as MessageKey) })}
      className="inline-flex size-5 items-center justify-center rounded-full text-muted-foreground hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring" onClick={() => setOpen(value => !value)}>
      <CircleHelp aria-hidden="true" className="size-4" />
    </button>
    {open && <span id={id} role="note" className="absolute top-6 left-0 z-20 w-64 rounded-md border bg-popover p-3 text-left text-xs leading-relaxed font-normal text-popover-foreground shadow-md">{t(`glossary.${term}.body` as MessageKey)}</span>}
  </span>;
}
