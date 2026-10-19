import { useRef } from "react";
import { ErrorState } from "@/components/shared/ErrorState";
import { useT } from "@/lib/i18n";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";

type Props = {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  pending?: boolean;
  /** Error from the last attempt (null/undefined when none); the dialog stays open so the user can retry or cancel. */
  error?: unknown;
  onOpenChange(open: boolean): void;
  onConfirm(): void;
};

/** Destructive confirmation. It has no Radix Trigger (the parent controls `open`), so it remembers the opener and refocuses it on close. */
export function ConfirmActionDialog({ open, title, description, confirmLabel, pending = false, error, onOpenChange, onConfirm }: Props) {
  const { t } = useT();
  const opener = useRef<HTMLElement | null>(null);
  return <AlertDialog open={open} onOpenChange={onOpenChange}>
    <AlertDialogContent
      onOpenAutoFocus={() => { opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null; }}
      onCloseAutoFocus={event => { event.preventDefault(); opener.current?.focus(); }}>
      <AlertDialogHeader><AlertDialogTitle>{title}</AlertDialogTitle><AlertDialogDescription>{description}</AlertDialogDescription></AlertDialogHeader>
      {error != null && <ErrorState error={error} />}
      <AlertDialogFooter>
        <AlertDialogCancel disabled={pending}>{t("common.cancel")}</AlertDialogCancel>
        <AlertDialogAction variant="destructive" disabled={pending} onClick={event => { event.preventDefault(); onConfirm(); }}>{confirmLabel}</AlertDialogAction>
      </AlertDialogFooter>
    </AlertDialogContent>
  </AlertDialog>;
}
