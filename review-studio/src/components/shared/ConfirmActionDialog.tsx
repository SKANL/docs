import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";

type Props = {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  pending?: boolean;
  /** Server error from the last attempt; the dialog stays open so the user can retry or cancel. */
  error?: string;
  onOpenChange(open: boolean): void;
  onConfirm(): void;
};

/** Destructive confirmation. Radix restores focus to the control that opened it. */
export function ConfirmActionDialog({ open, title, description, confirmLabel, pending = false, error, onOpenChange, onConfirm }: Props) {
  return <AlertDialog open={open} onOpenChange={onOpenChange}>
    <AlertDialogContent>
      <AlertDialogHeader><AlertDialogTitle>{title}</AlertDialogTitle><AlertDialogDescription>{description}</AlertDialogDescription></AlertDialogHeader>
      {error && <p className="text-sm text-destructive" role="alert">{error}</p>}
      <AlertDialogFooter>
        <AlertDialogCancel disabled={pending}>Cancel</AlertDialogCancel>
        <AlertDialogAction variant="destructive" disabled={pending} onClick={event => { event.preventDefault(); onConfirm(); }}>{confirmLabel}</AlertDialogAction>
      </AlertDialogFooter>
    </AlertDialogContent>
  </AlertDialog>;
}
