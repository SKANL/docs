import { useEffect, useState } from "react";
import { useApi } from "@/app/providers";
import { ErrorState } from "@/components/shared/ErrorState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ActionError, useAction } from "@/features/authoring/data";
import { CheckOutcome } from "./Issues";

/** Validates an installed template, or a pasted draft that is checked but never stored. */
export function TemplateValidationPanel({ initialName = "" }: { initialName?: string }) {
  const api = useApi();
  const [name, setName] = useState(initialName);
  const [draft, setDraft] = useState("");
  const [draftError, setDraftError] = useState<string | null>(null);
  useEffect(() => { if (initialName) setName(initialName); }, [initialName]);
  const validate = useAction((input: { name: string; draft?: Record<string, unknown> }) => api.validateTemplate!(input.name, input.draft), {
    success: result => result.passed ? `${result.name} passed validation.` : `${result.name} has validation issues.`,
  });

  function submit() {
    setDraftError(null);
    let parsed: Record<string, unknown> | undefined;
    if (draft.trim()) {
      try {
        const value: unknown = JSON.parse(draft);
        if (typeof value !== "object" || value === null || Array.isArray(value)) throw new Error("it must be a JSON object");
        parsed = value as Record<string, unknown>;
      } catch (error) {
        setDraftError(`The draft is not valid JSON: ${error instanceof Error ? error.message : "unreadable"}.`);
        return;
      }
    }
    validate.mutate({ name: name.trim(), draft: parsed });
  }

  return <section aria-label="Validate template" className="grid gap-3 rounded-lg border bg-card p-4">
    <h2 className="text-xl font-semibold">Validate template</h2>
    <form className="grid max-w-xl gap-3" onSubmit={event => { event.preventDefault(); if (name.trim()) submit(); }}>
      <div className="grid gap-1"><Label htmlFor="validate-name">Template name</Label><Input id="validate-name" autoComplete="off" value={name} onChange={event => setName(event.target.value)} /></div>
      <div className="grid gap-1"><Label htmlFor="validate-draft">Draft JSON (optional)</Label>
        <Textarea id="validate-draft" rows={6} className="font-mono text-xs" value={draft} onChange={event => setDraft(event.target.value)} />
        <p className="text-xs text-muted-foreground">A draft is checked in place of the stored file and is never written.</p></div>
      <Button type="submit" className="w-fit" disabled={!name.trim() || validate.isPending}>{validate.isPending ? "Validating…" : "Validate"}</Button>
    </form>
    {draftError && <ErrorState title="Cannot validate" message={draftError} />}
    <ActionError action={validate} what="validate the template" />
    {validate.data && <section role="status" aria-label="Validation result" className="grid gap-2 rounded-md border p-3">
      <CheckOutcome passed={validate.data.passed} label={validate.data.name} issues={validate.data.issues} />
    </section>}
  </section>;
}
