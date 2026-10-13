import { useEffect, useState, type FormEvent } from "react";
import { useApi } from "@/app/providers";
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
  const [step, setStep] = useState<"form" | "confirm">("form");
  const [destination, setDestination] = useState("");
  const [policy, setPolicy] = useState<RunPolicy>("release");
  const [format, setFormat] = useState(SERVER_DEFAULT);
  const publish = useAction((input: PublishInput) => api.publishDocument!(documentId, input), {
    success: result => `Published ${result.destination}.`,
    invalidate: [deliveryKeys.publications(workspaceId)],
    onDone: result => { onOpenChange(false); onPublished(result); },
  });
  useEffect(() => { if (open) { setStep("form"); setDestination(""); setPolicy("release"); setFormat(SERVER_DEFAULT); publish.reset(); } }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const request: PublishInput = { destination: destination.trim(), policy, ...(format === SERVER_DEFAULT ? {} : { format: format as OutputFormat }) };
  const review = (event: FormEvent) => { event.preventDefault(); if (request.destination) setStep("confirm"); };

  return <Dialog open={open} onOpenChange={next => { if (!publish.isPending) onOpenChange(next); }}>
    <DialogContent showCloseButton={false} aria-describedby="publish-description">
      <DialogHeader><DialogTitle>Publish</DialogTitle>
        <DialogDescription id="publish-description">Copies the verified build output to a destination inside the document&apos;s release folder. The server decides whether the policy allows it.</DialogDescription></DialogHeader>
      {step === "form" ? <form onSubmit={review} className="grid gap-4">
        <div className="grid gap-2"><Label htmlFor="publish-destination">Destination</Label>
          <Input id="publish-destination" autoComplete="off" required placeholder="final/report.html" value={destination} onChange={event => setDestination(event.target.value)} />
          <p className="text-xs text-muted-foreground">Relative to the release folder. Absolute paths and &quot;..&quot; are refused by the server.</p></div>
        <div className="flex flex-wrap gap-4">
          <div className="grid gap-2"><Label htmlFor="publish-policy">Policy</Label>
            <Select value={policy} onValueChange={value => setPolicy(value as RunPolicy)}>
              <SelectTrigger id="publish-policy" aria-label="Policy" className="w-36"><SelectValue /></SelectTrigger>
              <SelectContent>{policies.map(value => <SelectItem key={value} value={value}>{value}</SelectItem>)}</SelectContent>
            </Select></div>
          <div className="grid gap-2"><Label htmlFor="publish-format">Format</Label>
            <Select value={format} onValueChange={setFormat}>
              <SelectTrigger id="publish-format" aria-label="Format" className="w-36"><SelectValue /></SelectTrigger>
              <SelectContent>{formats.map(value => <SelectItem key={value} value={value}>{value === SERVER_DEFAULT ? "server default" : value}</SelectItem>)}</SelectContent>
            </Select></div>
        </div>
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button type="submit" disabled={!request.destination}>Review publish</Button>
        </DialogFooter>
      </form> : <div className="grid gap-4">
        <dl aria-label="Publish summary" className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-[8rem_1fr]">
          <dt className="text-muted-foreground">Document</dt><dd>{documentId}</dd>
          <dt className="text-muted-foreground">Destination</dt><dd className="break-all">{request.destination}</dd>
          <dt className="text-muted-foreground">Policy</dt><dd>{policy}</dd>
          <dt className="text-muted-foreground">Format</dt><dd>{format === SERVER_DEFAULT ? "server default" : format}</dd>
        </dl>
        <p className="text-sm text-muted-foreground">Nothing is published until the server confirms it. If the policy denies this, the reason appears here.</p>
        <ActionError action={publish} what="publish" />
        <DialogFooter>
          <Button type="button" variant="ghost" disabled={publish.isPending} onClick={() => { publish.reset(); setStep("form"); }}>Back</Button>
          <Button type="button" disabled={publish.isPending} onClick={() => publish.mutate(request)}>{publish.isPending ? "Publishing…" : "Confirm and publish"}</Button>
        </DialogFooter>
      </div>}
    </DialogContent>
  </Dialog>;
}
