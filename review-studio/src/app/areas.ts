import { FileText, Home, PackageCheck, Play, Settings2, ShieldCheck, Wrench, type LucideIcon } from "lucide-react";

type Area = { id: string; label: string; path: string; summary: string; icon: LucideIcon; secondary?: boolean };

/** Task areas from the redesign spec's information architecture. */
export const areas: Area[] = [
  { id: "home", label: "Home", path: "/", summary: "Current document readiness, blockers, recent runs, and the next safe action.", icon: Home },
  { id: "authoring", label: "Authoring", path: "/authoring", summary: "Sources, classification, assets, context, sections, and revisions.", icon: FileText },
  { id: "pipeline", label: "Pipeline", path: "/pipeline", summary: "Planning, preparation, builds, verification, run history, and watch.", icon: Play },
  { id: "review", label: "Review", path: "/review", summary: "Findings, artifacts, previews, visual baselines, passports, inspect, and diff.", icon: ShieldCheck },
  { id: "delivery", label: "Delivery", path: "/delivery", summary: "Package, publish, releases, and evidence.", icon: PackageCheck },
  { id: "configure", label: "Configure", path: "/configure", summary: "Workspaces, documents, templates, plugins, rules, and diagnostics.", icon: Settings2 },
  { id: "tools", label: "Tools", path: "/tools", summary: "Collection, rules, DOCX, and translation tools.", icon: Wrench, secondary: true },
];

/** Capability `slice` (S0-S6, from the catalogue) to the task area that hosts it. */
const sliceArea: Record<string, string> = { S0: "/", S1: "/configure/workspaces", S2: "/authoring", S3: "/pipeline", S4: "/review", S5: "/delivery", S6: "/configure" };
export const areaPathForSlice = (slice: string) => sliceArea[slice] ?? "/";
