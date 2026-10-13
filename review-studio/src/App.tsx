import { useEffect, useMemo, useState } from "react";
import type { ReviewApi } from "./api/models";
import { createReviewApi } from "./api/factory";
import { ApiStatus } from "./components/ApiStatus";
import { LegacyRoute } from "./app/legacy-pages";
import { WorkspaceDocumentPage } from "./features/workspace/WorkspaceDocumentPage";
import "./styles.css";

const navigation = [["overview","Overview"],["workspace","Workspace setup"],["runs","Run history"],["findings","Findings inbox"],["artifacts","Artifact preview"],["passport","Evidence passport"],["graph","Semantic graph"],["templates","Templates"],["plugins","Plugins"],["baselines","Baselines"],["revisions","Revisions"],["publication","Publication status"]] as const;

function useHashRoute() {
  const [route, setRoute] = useState(() => location.hash.slice(1) || "overview");
  useEffect(() => { const onChange = () => setRoute(location.hash.slice(1) || "overview"); addEventListener("hashchange", onChange); return () => removeEventListener("hashchange", onChange); }, []);
  return route;
}

function CommandPalette({open,onClose,go}:{open:boolean;onClose:()=>void;go:(route:string)=>void}) {
  useEffect(() => { if (!open) return; const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); }; addEventListener("keydown", onKey); return () => removeEventListener("keydown", onKey); }, [open,onClose]);
  if (!open) return null;
  return <div className="command-overlay" onMouseDown={onClose}><section className="command-dialog" role="dialog" aria-modal="true" aria-label="Command palette" onMouseDown={event => event.stopPropagation()}><div className="card-title"><h2>Jump to</h2><button className="button secondary" onClick={onClose}>Close</button></div><div className="command-list">{navigation.map(([id,label]) => <button className="command-item" key={id} onClick={() => {go(id);onClose();}}>{label}</button>)}</div></section></div>;
}

export default function App({api:providedApi}:{api?:ReviewApi} = {}) {
  const route = useHashRoute();
  const [commandOpen,setCommandOpen] = useState(false);
  const api = useMemo(() => providedApi ?? createReviewApi(), [providedApi]);
  const go = (next:string) => { location.hash = next; requestAnimationFrame(() => document.getElementById("main")?.focus()); };
  useEffect(() => { const onKey = (event:KeyboardEvent) => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") { event.preventDefault(); setCommandOpen(true); } }; addEventListener("keydown",onKey); return () => removeEventListener("keydown",onKey); }, []);
  return <div className="app"><a className="skip" href="#main" onClick={event => {event.preventDefault();document.getElementById("main")?.focus();}}>Skip to content</a><header><a className="brand" href="#overview"><span className="brand-mark">R</span><span>Review <b>Studio</b></span></a><div className="header-meta"><ApiStatus api={api}/><button className="icon-button" aria-label="Open command menu" onClick={() => setCommandOpen(true)}>⌘ K</button><button className="avatar" aria-label="Account menu">Account</button></div></header><div className="layout"><aside><div className="workspace-label">WORKSPACE</div><button className="workspace-switcher" onClick={() => go("workspace")} aria-label="Manage workspaces">Manage workspaces <span>↗</span></button><nav aria-label="Review Studio"><ul>{navigation.map(([id,label]) => <li key={id}><a href={`#${id}`} aria-current={route === id ? "page" : undefined}>{label}</a></li>)}</ul></nav><div className="sidebar-footer"><span className="avatar small">R</span><span><b>Review participant</b><small>Configured account</small></span></div></aside><main id="main" tabIndex={-1}>{route === "workspace" ? <WorkspaceDocumentPage api={api}/> : <LegacyRoute route={route} api={api} go={go}/>}</main></div><footer><span>Review Studio foundation</span><span>API adapter: configured Review API</span></footer><CommandPalette open={commandOpen} onClose={() => setCommandOpen(false)} go={go}/></div>;
}

