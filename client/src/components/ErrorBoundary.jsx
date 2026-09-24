import { Component } from "react";

/**
 * Contains a render crash to the page it happened on.
 *
 * Without this, one exception anywhere under the router blanked the whole
 * console -- rail, status strip and all -- and the only way back was a reload,
 * which on the Live wall also tears down every video. With it, the shell stays
 * up, the failed page says what happened, and navigating anywhere else
 * (`resetKey` is the pathname) clears the error and renders normally. The same
 * shape as frontend-v5's page-level boundary.
 */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null, resetKey: props.resetKey };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    // The console's own log panel reads the FE tab from api(), not console
    // output; this keeps the stack available to anyone with devtools open.
    console.error("Page render failed:", error, info?.componentStack);
  }

  // Navigating away clears the error. Derived from props rather than keyed on
  // the path: a key would remount every page on every navigation -- on the Live
  // view that tears down each video player just to change camera.
  static getDerivedStateFromProps(props, state) {
    if (props.resetKey === state.resetKey) return null;
    return { resetKey: props.resetKey, error: null };
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="page-error" role="alert">
        <h2>This page hit an error</h2>
        <p>The rest of the console is unaffected. Try the page again, or go to another view.</p>
        <pre className="page-error-detail">{String(this.state.error?.message ?? this.state.error)}</pre>
        <button type="button" className="primary" onClick={() => this.setState({ error: null })}>
          Try again
        </button>
      </div>
    );
  }
}
