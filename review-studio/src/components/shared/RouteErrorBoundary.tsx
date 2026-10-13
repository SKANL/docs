import { Component, type ReactNode } from "react";
import { ErrorState } from "@/components/shared/ErrorState";
import { Button } from "@/components/ui/button";

/** Keeps a failed route chunk (e.g. a stale deployment) from blanking the whole app. */
export class RouteErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  render() {
    if (!this.state.error) return this.props.children;
    return <div className="grid gap-3">
      <ErrorState title="Could not load this page" message={this.state.error.message} />
      <div><Button type="button" variant="outline" size="sm" onClick={() => window.location.reload()}>Reload</Button></div>
    </div>;
  }
}
