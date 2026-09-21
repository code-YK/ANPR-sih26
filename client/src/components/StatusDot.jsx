// Extracted from Live/AnalyticsToggle.jsx so CameraTile.jsx (a per-tile
// running/queued/stopped indicator, not just the focused camera's side
// panel) can render the exact same three states the same way.
export default function StatusDot({ state, title }) {
  const cls =
    state === "running" ? "status-dot-running"
      : state === "queued" ? "status-dot-queued"
        : "status-dot-stopped";
  return <span className={`status-dot ${cls}`} title={title} />;
}
