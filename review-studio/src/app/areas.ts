import { FileText, Home, PackageCheck, Play, Settings2, ShieldCheck, Wrench, type LucideIcon } from "lucide-react";

export type Area = { id: string; label: string; path: string; slice: string; summary: string; icon: LucideIcon; secondary?: boolean };

/** Task areas from the redesign spec's information architecture. `slice` names who delivers the real page. */
export const areas: Area[] = [
  { id: "home", label: "Home", path: "/", slice: "Slice 3 (Task S3.2)", summary: "Current document readiness, blockers, recent runs, and the next safe action.", icon: Home },
  { id: "authoring", label: "Authoring", path: "/authoring", slice: "Slice 2 (Task S2.3)", summary: "Sources, classification, assets, context, sections, and revisions.", icon: FileText },
  { id: "pipeline", label: "Pipeline", path: "/pipeline", slice: "Slice 3 (Task S3.2)", summary: "Planning, preparation, builds, verification, run history, and watch.", icon: Play },
  { id: "review", label: "Review", path: "/review", slice: "Slice 4 (Task S4.2)", summary: "Findings, artifacts, previews, visual baselines, passports, inspect, and diff.", icon: ShieldCheck },
  { id: "delivery", label: "Delivery", path: "/delivery", slice: "Slice 5 (Task S5.2)", summary: "Package, publish, releases, and evidence.", icon: PackageCheck },
  { id: "configure", label: "Configure", path: "/configure", slice: "Slice 6 (Task S6.3)", summary: "Workspaces, documents, templates, plugins, rules, and diagnostics.", icon: Settings2 },
  { id: "tools", label: "Tools", path: "/tools", slice: "Slice 6 (Task S6.3)", summary: "Collection, rules, DOCX, and translation tools.", icon: Wrench, secondary: true },
];


/** Capability `slice` (S0-S6, from the catalogue) to the task area that hosts it. */
const sliceArea: Record<string, string> = { S0: "/", S1: "/configure/workspaces", S2: "/authoring", S3: "/pipeline", S4: "/review", S5: "/delivery", S6: "/configure" };
export const areaPathForSlice = (slice: string) => sliceArea[slice] ?? "/";

export const legacyScreens = [["overview", "Overview"], ["runs", "Run history"], ["findings", "Findings inbox"], ["artifacts", "Artifact preview"], ["passport", "Evidence passport"], ["graph", "Semantic graph"], ["templates", "Templates"], ["plugins", "Plugins"], ["baselines", "Baselines"], ["revisions", "Revisions"], ["publication", "Publication status"]] as const;
