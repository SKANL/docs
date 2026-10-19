import { useEffect, useState, type FormEvent } from "react";
import { useApi } from "@/app/providers";
import { useT } from "@/lib/i18n";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ActionError, useAction } from "@/lib/actions";
import type { OutputFormat, RunPolicy } from "@/api/domains/pipeline";
import type { PublicationResult, PublishInput } from "@/api/domains/delivery";
import { deliveryKeys } from "./data";

const policies: RunPolicy[] = ["draft", "strict", "release"];
const SERVER_DEFAULT = "default";
const formats = [SERVER_DEFAULT, "docx", "pdf", "html"];

type Props = { open: boolean; workspaceId: string | null; documentId: string; onOpenChange(open: boolean): void; onPublished(result: PublicationResult): void };

/**
 * Two steps on purpose: fill in, then confirm what will be sent. The dialog only closes on a 201;
 * every denial stays here, verbatim, with a retry that re-sends the same request.
 */
export function PublishDialog({ open, workspaceId, documentId, onOpenChange, onPublished }: Props) {
  const api = useApi();
  const { t } = useT();
  const [step, setStep] = useState<"form" | "confirm">("form");
  const [destination, setDestination] = useState("");
  const [policy, setPolicy] = useState<RunPolicy>("release");
  const [format, setFormat] = useState(SERVER_DEFAULT);
  const publish = useAction((input: PublishInput) => api.publishDocument!(documentId, input), {
    success: result => t("dl.publishedToast", { destination: result.destination }),
    invalidate: [deliveryKeys.publications(workspaceId)],
    onDone: result => { onOpenChange(false); onPublished(result); },
  });
  useEffect(() => { if (open) { setStep("form"); setDestination(""); setPolicy("release"); setFormat(SERVER_DEFAULT); publish.reset(); } }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const request: PublishInput = { destination: destination.trim(), policy, ...(format === SERVER_DEFAULT ? {} : { format: format as OutputFormat }) };
  const review = (event: FormEvent) => { event.preventDefault(); if (request.destination) setStep("confirm"); };

  return <Dialog open={open} onOpenChange={next => { if (!publish.isPending) onOpenChange(next); }}>
    <DialogContent showCloseButton={false} aria-describedby="publish-description">
      <DialogHeader><DialogTitle>{t("term.deliver")}</DialogTitle>
        <DialogDescription id="publish-description">{t("dl.pub.body")}</DialogDescription></DialogHeader>
      {step === "form" ? <form onSubmit={review} className="grid gap-4">
        <div className="grid gap-2"><Label htmlFor="publish-destination">{t("dl.pub.destination")}</Label>
          <Input id="publish-destination" autoComplete="off" required placeholder="final/report.html" value={destination} onChange={event => setDestination(event.target.value)} />
          <p className="text-xs text-muted-foreground">{t("dl.pub.hint")}</p></div>
        <div className="flex flex-wrap gap-4">
          <div className="grid gap-2"><Label htmlFor="publish-policy">{t("dl.policy")}</Label>
            <Select value={policy} onValueChange={value => setPolicy(value as RunPolicy)}>
              <SelectTrigger id="publish-policy" aria-label={t("dl.policy")} className="w-36"><SelectValue /></SelectTrigger>
              <SelectContent>{policies.map(value => <SelectItem key={value} value={value}>{t(`pl.policy.${value}`)}</SelectItem>)}</SelectContent>
            </Select></div>
          <div className="grid gap-2"><Label htmlFor="publish-format">{t("dl.format")}</Label>
            <Select value={format} onValueChange={setFormat}>
              <SelectTrigger id="publish-format" aria-label={t("dl.format")} className="w-36"><SelectValue /></SelectTrigger>
              <SelectContent>{formats.map(value => <SelectItem key={value} value={value}>{value === SERVER_DEFAULT ? t("dl.pub.serverDefault") : value}</SelectItem>)}</SelectContent>
            </Select></div>
        </div>
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>{t("common.cancel")}</Button>
          <Button type="submit" disabled={!request.destination}>{t("dl.pub.review")}</Button>
        </DialogFooter>
      </form> : <div className="grid gap-4">
        <dl aria-label={t("dl.pub.summary")} className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-[8rem_1fr]">
          <dt className="text-muted-foreground">{t("dl.pub.document")}</dt><dd>{documentId}</dd>
          <dt className="text-muted-foreground">{t("dl.pub.destination")}</dt><dd className="break-all">{request.destination}</dd>
          <dt className="text-muted-foreground">{t("dl.policy")}</dt><dd>{t(`pl.policy.${policy}`)}</dd>
          <dt className="text-muted-foreground">{t("dl.format")}</dt><dd>{format === SERVER_DEFAULT ? t("dl.pub.serverDefault") : format}</dd>
        </dl>
        <p className="text-sm text-muted-foreground">{t("dl.pub.notice")}</p>
        <ActionError action={publish} what={t("act.publish")} />
        <DialogFooter>
          <Button type="button" variant="ghost" disabled={publish.isPending} onClick={() => { publish.reset(); setStep("form"); }}>{t("dl.pub.back")}</Button>
          <Button type="button" disabled={publish.isPending} onClick={() => publish.mutate(request)}>{publish.isPending ? t("dl.pub.publishing") : t("dl.pub.confirm")}</Button>
        </DialogFooter>
      </div>}
    </DialogContent>
  </Dialog>;
}
