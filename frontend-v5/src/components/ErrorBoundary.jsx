import { TriangleAlert } from "lucide-react";
import { Component } from "react";

import { Button, EmptyState } from "./ui.jsx";

/**
 * Contains a render error to the subtree that threw. Without one, React 19
 * unmounts the whole root and the console goes blank until a reload.
 *
 * `fallback` defaults to nothing, which suits background components (syncs,
 * docks). Pass `resetKey` to clear the error when it changes, e.g. the route.
 */
export class ErrorBoundary extends Component {
  state = { error: null, resetKey: this.props.resetKey };

  static getDerivedStateFromError(error) {
    return { error };
  }

  static getDerivedStateFromProps(props, state) {
    if (props.resetKey !== state.resetKey) return { error: null, resetKey: props.resetKey };
    return null;
  }

  componentDidCatch(error, info) {
    console.error(`[${this.props.name ?? "boundary"}]`, error, info?.componentStack);
  }

  render() {
    if (this.state.error) return this.props.fallback ?? null;
    return this.props.children;
  }
}

export function PageError() {
  return (
    <EmptyState
      icon={<TriangleAlert />}
      title="This view stopped working"
      action={
        <Button variant="primary" onClick={() => window.location.reload()}>
          Reload
        </Button>
      }
    >
      Running workers are not affected.
    </EmptyState>
  );
}
