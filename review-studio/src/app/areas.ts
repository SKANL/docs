import type { MessageKey } from "@/lib/i18n";
import { FileText, Home, PackageCheck, Play, Settings2, ShieldCheck, Wrench, type LucideIcon } from "lucide-react";

/** Who sees an area in navigation: everyone, people writing in the UI, or people who opted into Advanced. */
type Reach = "base" | "write" | "advanced";
type Area = { id: string; label: string; navKey: MessageKey; path: string; summary: string; icon: LucideIcon; reach: Reach; secondary?: boolean };

/** Task areas from the redesign spec's information architecture. */
export const areas: Area[] = [
  { id: "home", navKey: "nav.home", reach: "base", label: "Home", path: "/", summary: "Current document readiness, blockers, recent runs, and the next safe action.", icon: Home },
  { id: "authoring", navKey: "nav.write", reach: "write", label: "Authoring", path: "/authoring", summary: "Sources, classification, assets, context, sections, and revisions.", icon: FileText },
  { id: "pipeline", navKey: "nav.runs", reach: "base", label: "Pipeline", path: "/pipeline", summary: "Planning, preparation, builds, verification, run history, and watch.", icon: Play },
  { id: "review", navKey: "nav.review", reach: "base", label: "Review", path: "/review", summary: "Findings, artifacts, previews, visual baselines, passports, inspect, and diff.", icon: ShieldCheck },
  { id: "delivery", navKey: "nav.delivery", reach: "base", label: "Delivery", path: "/delivery", summary: "Package, publish, releases, and evidence.", icon: PackageCheck },
  { id: "configure", navKey: "nav.config", reach: "advanced", label: "Configure", path: "/configure", summary: "Workspaces, documents, templates, plugins, rules, and diagnostics.", icon: Settings2 },
  { id: "tools", navKey: "nav.tools", reach: "advanced", label: "Tools", path: "/tools", summary: "Collection, rules, DOCX, and translation tools.", icon: Wrench, secondary: true },
];

/** Areas shown in navigation, the palette and route maps. Hidden areas keep their URLs; they are only unlisted. */
export function visibleAreas(mode: "supervise" | "write", advanced: boolean): Area[] {
  return areas.filter(area => area.reach === "base" || (area.reach === "write" && mode === "write") || (area.reach === "advanced" && advanced));
}

/** Capability `slice` (S0-S6, from the catalogue) to the task area that hosts it. */
const sliceArea: Record<string, string> = { S0: "/", S1: "/configure/workspaces", S2: "/authoring", S3: "/pipeline", S4: "/review", S5: "/delivery", S6: "/configure" };
export const areaPathForSlice = (slice: string) => sliceArea[slice] ?? "/";
