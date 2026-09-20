import type {Status} from "../api/models";
export function StatusBadge({status}:{status:Status}){const label={passed:"Passed",warnings:"Warnings",failed:"Failed",unverified:"Unverified"}[status];return <span className={"status status-"+status}><span aria-hidden="true">{status==="passed"?"✓":status==="failed"?"×":status==="warnings"?"!":"?"}</span> {label}</span>}
