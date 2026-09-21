import { useEffect, useRef } from "react";

/**
 * Calls `callback` immediately, then every `intervalMs`, with cleanup on
 * unmount/dependency change. One implementation, used everywhere something
 * polls (Alerts, analytics status) -- ad-hoc setInterval calls in components
 * are how a poll survives navigation and stacks up.
 */
export function usePolling(callback, intervalMs, enabled = true) {
  const savedCallback = useRef(callback);
  savedCallback.current = callback;

  useEffect(() => {
    if (!enabled) return undefined;
    let cancelled = false;

    const tick = () => {
      if (!cancelled) savedCallback.current();
    };

    tick();
    const id = setInterval(tick, intervalMs);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [intervalMs, enabled]);
}
