import { useEffect, useState } from "react";
import { useApi } from "@/app/providers";
import { ErrorState } from "@/components/shared/ErrorState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ActionError, useAction } from "@/lib/actions";
import { useT } from "@/lib/i18n";
import { CheckOutcome } from "./Issues";

/** Validates an installed template, or a pasted draft that is checked but never stored. */
export function TemplateValidationPanel({ initialName = "" }: { initialName?: string }) {
  const { t } = useT();
  const api = useApi();
  const [name, setName] = useState(initialName);
  const [draft, setDraft] = useState("");
  const [draftError, setDraftError] = useState<string | null>(null);
  useEffect(() => { if (initialName) setName(initialName); }, [initialName]);
  const validate = useAction((input: { name: string; draft?: Record<string, unknown> }) => api.validateTemplate!(input.name, input.draft), {
    success: result => result.passed ? t("tv.passedToast", { name: result.name }) : t("tv.issuesToast", { name: result.name }),
  });

  function submit() {
    setDraftError(null);
    let parsed: Record<string, unknown> | undefined;
    if (draft.trim()) {
      try {
        const value: unknown = JSON.parse(draft);
        if (typeof value !== "object" || value === null || Array.isArray(value)) throw new Error(t("tv.mustObject"));
        parsed = value as Record<string, unknown>;
      } catch (error) {
        setDraftError(t("tv.badJson", { reason: error instanceof Error ? error.message : t("tv.unreadable") }));
        return;
      }
    }
    validate.mutate({ name: name.trim(), draft: parsed });
  }

  return <section aria-label={t("tv.heading")} className="grid gap-3 rounded-lg border bg-card p-4">
    <h2 className="text-xl font-semibold">{t("tv.heading")}</h2>
    <form className="grid max-w-xl gap-3" onSubmit={event => { event.preventDefault(); if (name.trim()) submit(); }}>
      <div className="grid gap-1"><Label htmlFor="validate-name">{t("tv.name")}</Label><Input id="validate-name" autoComplete="off" value={name} onChange={event => setName(event.target.value)} /></div>
      <div className="grid gap-1"><Label htmlFor="validate-draft">{t("tv.draft")}</Label>
        <Textarea id="validate-draft" rows={6} className="font-mono text-xs" value={draft} onChange={event => setDraft(event.target.value)} />
        <p className="text-xs text-muted-foreground">{t("tv.hint")}</p></div>
      <Button type="submit" className="w-fit" disabled={!name.trim() || validate.isPending}>{validate.isPending ? t("tv.validating") : t("tv.validate")}</Button>
    </form>
    {draftError && <ErrorState title={t("tv.cannot")} message={draftError} />}
    <ActionError action={validate} what={t("act.validateTemplate")} />
    {validate.data && <section role="status" aria-label={t("tv.result")} className="grid gap-2 rounded-md border p-3">
      <CheckOutcome passed={validate.data.passed} label={validate.data.name} issues={validate.data.issues} />
    </section>}
  </section>;
}
