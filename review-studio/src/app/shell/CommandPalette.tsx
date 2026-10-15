import { useNavigate } from "react-router-dom";
import { areaPathForSlice, visibleAreas } from "@/app/areas";
import { useMode } from "@/app/mode";
import { CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { useT } from "@/lib/i18n";
import { useCapabilityActions } from "@/lib/capability-registry";

type Props = { open: boolean; onOpenChange(open: boolean): void };

/** Navigation plus capability actions. Capabilities that are not `enabled` never become items. */
export function CommandPalette({ open, onOpenChange }: Props) {
  const navigate = useNavigate();
  const { t } = useT();
  const { mode, advanced } = useMode();
  const { data: capabilities = [] } = useCapabilityActions({ enabled: open });
  const go = (path: string) => { onOpenChange(false); navigate(path); };
  return <CommandDialog open={open} onOpenChange={onOpenChange} title={t("palette.title")} description={t("palette.description")}>
    <CommandInput placeholder={t("palette.placeholder")} />
    <CommandList>
      <CommandEmpty>{t("palette.empty")}</CommandEmpty>
      <CommandGroup heading={t("palette.goTo")}>
        {visibleAreas(mode, advanced).map(({ id, navKey, path }) => <CommandItem key={id} value={t(navKey)} onSelect={() => go(path)}>{t(navKey)}</CommandItem>)}
      </CommandGroup>
      {capabilities.some(item => item.enabled) && <CommandGroup heading={t("palette.capabilities")}>
        {capabilities.filter(item => item.enabled).map(item => <CommandItem key={item.id} value={item.cli_command ?? item.id} onSelect={() => go(areaPathForSlice(item.slice))}>{item.cli_command ?? item.id}</CommandItem>)}
      </CommandGroup>}
    </CommandList>
  </CommandDialog>;
}
