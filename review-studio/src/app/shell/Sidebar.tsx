import { NavLink } from "react-router-dom";
import { visibleAreas } from "@/app/areas";
import { useMode } from "@/app/mode";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";

const link = ({ isActive }: { isActive: boolean }) => cn(
  "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium text-sidebar-foreground/80 hover:bg-sidebar-accent hover:text-sidebar-foreground",
  isActive && "bg-sidebar-accent text-sidebar-foreground shadow-[inset_3px_0_0_var(--primary)]",
);

export function Sidebar() {
  const { t } = useT();
  const { mode, advanced } = useMode();
  const shown = visibleAreas(mode, advanced);
  const primary = shown.filter(area => !area.secondary);
  const secondary = shown.filter(area => area.secondary);
  return <aside className="flex shrink-0 flex-col gap-6 bg-sidebar px-3 py-5 text-sidebar-foreground md:w-60">
    <nav aria-label={t("nav.areas")}>
      <ul className="flex gap-1 overflow-x-auto md:flex-col">
        {primary.map(({ id, navKey, path, icon: Icon }) => <li key={id}>
          <NavLink to={path} end={path === "/"} className={link}><Icon aria-hidden="true" className="size-4" />{t(navKey)}</NavLink>
        </li>)}
      </ul>
    </nav>
    {secondary.length > 0 && <nav aria-label={t("nav.specialist")}>
      <ul className="flex flex-col gap-1">
        {secondary.map(({ id, navKey, path, icon: Icon }) => <li key={id}>
          <NavLink to={path} className={link}><Icon aria-hidden="true" className="size-4" />{t(navKey)}</NavLink>
        </li>)}
      </ul>
    </nav>}
  </aside>;
}
