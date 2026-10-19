import { Component, type ReactNode } from "react";
import { ErrorState } from "@/components/shared/ErrorState";
import { Button } from "@/components/ui/button";
import { useT } from "@/lib/i18n";

function Failed({ error }: { error: Error }) {
  const { t } = useT();
  return <div className="grid gap-3">
    <ErrorState title={t("error.pageFailed")} error={error} />
    <div><Button type="button" variant="outline" size="sm" onClick={() => window.location.reload()}>{t("error.reload")}</Button></div>
  </div>;
}

/** Keeps a failed route chunk (e.g. a stale deployment) from blanking the whole app. */
export class RouteErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  render() {
    return this.state.error ? <Failed error={this.state.error} /> : this.props.children;
  }
}
