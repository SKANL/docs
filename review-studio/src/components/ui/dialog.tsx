import * as DialogPrimitive from "@radix-ui/react-dialog";
import { forwardRef, type ComponentPropsWithoutRef, type ElementRef } from "react";
import { cn } from "../../lib/cn";

export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;
export const DialogPortal = DialogPrimitive.Portal;
export const DialogOverlay = forwardRef<ElementRef<typeof DialogPrimitive.Overlay>, ComponentPropsWithoutRef<typeof DialogPrimitive.Overlay>>(({ className, ...props }, ref) => (
  <DialogPrimitive.Overlay ref={ref} className={cn("ui-dialog-overlay", className)} {...props} />
));
DialogOverlay.displayName = DialogPrimitive.Overlay.displayName;
export const DialogContent = forwardRef<ElementRef<typeof DialogPrimitive.Content>, ComponentPropsWithoutRef<typeof DialogPrimitive.Content>>(({ className, ...props }, ref) => (
  <DialogPortal><DialogOverlay /><DialogPrimitive.Content ref={ref} className={cn("ui-dialog-content", className)} {...props} /></DialogPortal>
));
DialogContent.displayName = DialogPrimitive.Content.displayName;
export const DialogTitle = DialogPrimitive.Title;
export const DialogDescription = DialogPrimitive.Description;
export function DialogHeader({ className, ...props }: ComponentPropsWithoutRef<"div">) { return <div className={cn("ui-dialog-header", className)} {...props} />; }
export function DialogFooter({ className, ...props }: ComponentPropsWithoutRef<"div">) { return <div className={cn("ui-dialog-footer", className)} {...props} />; }
