import { NavLink } from "react-router-dom";
import { areas, legacyScreens } from "@/app/areas";
import { cn } from "@/lib/utils";

const link = ({ isActive }: { isActive: boolean }) => cn(
  "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium text-sidebar-foreground/80 hover:bg-sidebar-accent hover:text-sidebar-foreground",
  isActive && "bg-sidebar-accent text-sidebar-foreground shadow-[inset_3px_0_0_var(--primary)]",
);

export function Sidebar() {
  return <aside className="flex shrink-0 flex-col gap-6 bg-sidebar px-3 py-5 text-sidebar-foreground md:w-60">
    <nav aria-label="Task areas">
      <ul className="flex gap-1 overflow-x-auto md:flex-col">
        {areas.map(({ id, label, path, icon: Icon }) => <li key={id}>
          <NavLink to={path} end={path === "/"} className={link}><Icon aria-hidden="true" className="size-4" />{label}</NavLink>
        </li>)}
      </ul>
    </nav>
    <nav aria-label="Legacy screens" className="hidden md:block">
      <p className="px-3 pb-2 text-[11px] font-semibold tracking-widest text-sidebar-foreground/60 uppercase">Legacy screens</p>
      <ul className="flex flex-col gap-0.5">
        {legacyScreens.map(([id, label]) => <li key={id}><NavLink to={`/legacy/${id}`} className={link}>{label}</NavLink></li>)}
      </ul>
    </nav>
  </aside>;
}
