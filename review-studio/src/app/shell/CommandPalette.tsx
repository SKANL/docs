import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { areaPathForSlice, areas } from "@/app/areas";
import { useApi } from "@/app/providers";
import { CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { loadCapabilityActions } from "@/lib/capability-registry";

type Props = { open: boolean; onOpenChange(open: boolean): void };

/** Navigation plus capability actions. Capabilities that are not `enabled` never become items. */
export function CommandPalette({ open, onOpenChange }: Props) {
  const api = useApi();
  const navigate = useNavigate();
  const { data: capabilities = [] } = useQuery({ queryKey: ["capabilities"], queryFn: () => loadCapabilityActions(api), enabled: open });
  const go = (path: string) => { onOpenChange(false); navigate(path); };
  return <CommandDialog open={open} onOpenChange={onOpenChange} title="Command palette" description="Jump to a task area or open where a capability lives.">
    <CommandInput placeholder="Type a command or search…" />
    <CommandList>
      <CommandEmpty>No matching command.</CommandEmpty>
      <CommandGroup heading="Go to">
        {areas.map(({ id, label, path }) => <CommandItem key={id} value={label} onSelect={() => go(path)}>{label}</CommandItem>)}
      </CommandGroup>
      {capabilities.some(item => item.enabled) && <CommandGroup heading="Capabilities">
        {capabilities.filter(item => item.enabled).map(item => <CommandItem key={item.id} value={item.cli_command} onSelect={() => go(areaPathForSlice(item.slice))}>{item.cli_command}</CommandItem>)}
      </CommandGroup>}
    </CommandList>
  </CommandDialog>;
}
