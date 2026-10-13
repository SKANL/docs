import * as AlertDialogPrimitive from "@radix-ui/react-alert-dialog";
import { forwardRef, type ComponentPropsWithoutRef, type ElementRef } from "react";
import { cn } from "../../lib/cn";

export const AlertDialog = AlertDialogPrimitive.Root;
export const AlertDialogTrigger = AlertDialogPrimitive.Trigger;
export const AlertDialogAction = AlertDialogPrimitive.Action;
export const AlertDialogCancel = AlertDialogPrimitive.Cancel;
export const AlertDialogPortal = AlertDialogPrimitive.Portal;
export const AlertDialogOverlay = forwardRef<ElementRef<typeof AlertDialogPrimitive.Overlay>, ComponentPropsWithoutRef<typeof AlertDialogPrimitive.Overlay>>(({ className, ...props }, ref) => (
  <AlertDialogPrimitive.Overlay ref={ref} className={cn("ui-dialog-overlay", className)} {...props} />
));
AlertDialogOverlay.displayName = AlertDialogPrimitive.Overlay.displayName;
export const AlertDialogContent = forwardRef<ElementRef<typeof AlertDialogPrimitive.Content>, ComponentPropsWithoutRef<typeof AlertDialogPrimitive.Content>>(({ className, ...props }, ref) => (
  <AlertDialogPortal><AlertDialogOverlay /><AlertDialogPrimitive.Content ref={ref} className={cn("ui-dialog-content", className)} {...props} /></AlertDialogPortal>
));
AlertDialogContent.displayName = AlertDialogPrimitive.Content.displayName;
export const AlertDialogTitle = AlertDialogPrimitive.Title;
export const AlertDialogDescription = AlertDialogPrimitive.Description;
export function AlertDialogHeader({ className, ...props }: ComponentPropsWithoutRef<"div">) { return <div className={cn("ui-dialog-header", className)} {...props} />; }
export function AlertDialogFooter({ className, ...props }: ComponentPropsWithoutRef<"div">) { return <div className={cn("ui-dialog-footer", className)} {...props} />; }
