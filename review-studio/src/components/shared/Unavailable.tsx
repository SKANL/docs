/** Shown in place of an action whose capability the server does not offer. */
export function Unavailable({ children }: { children: string }) {
  return <p className="text-sm text-muted-foreground">{children}</p>;
}
