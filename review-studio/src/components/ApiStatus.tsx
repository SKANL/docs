import { useEffect, useState } from "react";
import type { ReviewApi } from "../api/models";
import { formatApiError } from "../api/client";

export function ApiStatus({ api }: { api: ReviewApi }) {
  const [state, setState] = useState<"checking" | "ready" | "unavailable">("checking");
  const [detail, setDetail] = useState("");
  useEffect(() => {
    if (!api.health) { setState("unavailable"); setDetail("Health endpoint is not available"); return; }
    let active = true;
    api.health().then(value => { if (active) { setState(value.ready ? "ready" : "unavailable"); setDetail(value.protocol ?? ""); } })
      .catch(error => { if (active) { setState("unavailable"); setDetail(formatApiError(error, "Review API")); } });
    return () => { active = false; };
  }, [api]);
  const label = state === "ready" ? "Review API ready" : state === "checking" ? "Checking Review API" : "Review API unavailable";
  return <span className={`chip api-status ${state}`} role="status" aria-live="polite" title={detail}>{label}</span>;
}
