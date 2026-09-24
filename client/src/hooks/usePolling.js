import { useEffect, useRef } from "react";

/**
 * Calls `callback` immediately, then again `intervalMs` after each call
 * *finishes*, until unmount or a dependency change. One implementation, used
 * everywhere something polls -- ad-hoc setInterval calls in components are how
 * a poll survives navigation and stacks up.
 *
 * Two properties matter more than the interval:
 *
 * - **Never overlapping.** The next call is scheduled when the previous one
 *   settles, not on a fixed clock. This used to be a plain setInterval, which
 *   keeps firing while earlier requests are still waiting: measured on the
 *   detector's 500ms telemetry poll, each request took 20-23s in the browser
 *   (0.3s from the shell) because ~40 of them were queued behind each other for
 *   the browser's six connections to the origin. A slow backend turned a
 *   polling interval into a request pile-up that starved every other call.
 *
 * - **Cancelled on unmount.** `callback` receives an AbortSignal that fires
 *   when the component goes away; pass it to api() (`api(path, { signal })`)
 *   so a request for a view the operator has already left stops holding a
 *   connection. Without it, leaving a camera and coming back found the previous
 *   visit's requests still ahead in the queue.
 */
export function usePolling(callback, intervalMs, enabled = true) {
  const savedCallback = useRef(callback);
  savedCallback.current = callback;

  useEffect(() => {
    if (!enabled) return undefined;
    const controller = new AbortController();
    let timer = null;

    const run = async () => {
      if (controller.signal.aborted) return;
      try {
        await savedCallback.current(controller.signal);
      } catch {
        // The callback owns its own error handling; a throw must not end the poll.
      }
      if (!controller.signal.aborted) timer = setTimeout(run, intervalMs);
    };

    run();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [intervalMs, enabled]);
}
