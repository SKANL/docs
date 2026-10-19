import { useNavigate } from "react-router-dom";
import { areaPathForSlice, isPathVisible, visibleAreas } from "@/app/areas";
import { useMode } from "@/app/mode";
import { CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { hasMessage, useT } from "@/lib/i18n";
import { useCapabilityActions } from "@/lib/capability-registry";

type Props = { open: boolean; onOpenChange(open: boolean): void };

/** Navigation plus capability actions. Capabilities that are not `enabled` never become items. */
export function CommandPalette({ open, onOpenChange }: Props) {
  const navigate = useNavigate();
  const { t } = useT();
  const { mode, advanced } = useMode();
  const { data: capabilities = [] } = useCapabilityActions({ enabled: open });
  // Same rule as the nav: a capability whose home area is unlisted only shows up when that area is reachable.
  const items = capabilities.filter(item => item.enabled && isPathVisible(areaPathForSlice(item.slice), mode, advanced));
  const go = (path: string) => { onOpenChange(false); navigate(path); };
  return <CommandDialog open={open} onOpenChange={onOpenChange} title={t("palette.title")} description={t("palette.description")}>
    <CommandInput placeholder={t("palette.placeholder")} />
    <CommandList>
      <CommandEmpty>{t("palette.empty")}</CommandEmpty>
      <CommandGroup heading={t("palette.goTo")}>
        {visibleAreas(mode, advanced).map(({ id, navKey, path }) => <CommandItem key={id} value={t(navKey)} onSelect={() => go(path)}>{t(navKey)}</CommandItem>)}
      </CommandGroup>
      {items.length > 0 && <CommandGroup heading={t("palette.capabilities")}>
        {items.map(item => {
          const key = `cap.${item.id}`;
          const label = hasMessage(key) ? t(key) : item.cli_command ?? item.id;
          const hint = advanced && item.cli_command && item.cli_command !== label ? item.cli_command : null;
          return <CommandItem key={item.id} value={hint ? `${label} ${hint}` : label} onSelect={() => go(areaPathForSlice(item.slice))}>
            {label}{hint && <span className="ml-auto text-xs text-muted-foreground">{hint}</span>}
          </CommandItem>;
        })}
      </CommandGroup>}
    </CommandList>
  </CommandDialog>;
}
