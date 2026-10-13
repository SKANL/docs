import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cn } from "../../lib/cn";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "default" | "secondary" | "outline" | "ghost" | "destructive"; size?: "default" | "sm" };

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(({ className, variant = "default", size = "default", ...props }, ref) => (
  <button ref={ref} className={cn("ui-button", `ui-button-${variant}`, size === "sm" && "ui-button-sm", className)} {...props} />
));
Button.displayName = "Button";
