// Copilot stream plumbing, kept free of React so it can be reasoned about
// (and tested) on its own.
//
// EventSource is GET-only, so POST /api/copilot/chat is read through
// fetch + ReadableStream instead. That makes SSE framing ours to do: a
// network chunk can split a `data:` line anywhere, so the parser buffers and
// only emits whole frames.

/** Incremental `data:` frame parser. Feed it text, get parsed events back. */
export function createSseParser() {
  let buffer = "";

  return {
    /** @returns {object[]} events completed by this chunk */
    push(text) {
      buffer += text;
      const events = [];
      let separator;
      // Frames end at a blank line; anything after the last one is a partial
      // frame and stays buffered for the next chunk.
      while ((separator = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, separator);
        buffer = buffer.slice(separator + 2);
        for (const line of frame.split("\n")) {
          if (!line.startsWith("data:")) continue;
          const payload = line.slice(5).trim();
          if (!payload) continue;
          try {
            events.push(JSON.parse(payload));
          } catch {
            // A malformed frame is dropped rather than killing the stream;
            // the turn still ends on its `done` event.
          }
        }
      }
      return events;
    },
  };
}

/**
 * Map a navigate_to result onto an in-app path.
 *
 * `//host` is rejected explicitly: it passes a naive "starts with /" check
 * but browsers read it as protocol-relative and would leave the console.
 * The path comes from our own backend, so this is defence in depth -- but
 * this is the one place model-influenced output becomes navigation, which is
 * where defence in depth belongs.
 */
export function navigationPath(result) {
  const path = result?.data?.path;
  if (typeof path !== "string") return null;
  if (!path.startsWith("/") || path.startsWith("//")) return null;
  // The backend emits frontend-v5's routes. Translate to this console's:
  //   /journeys[/plate] -> /journey[/plate]
  //   /live/<cameraId>  -> /live   (LiveView focuses a camera through local
  //                                 state, not the URL, so there is nothing
  //                                 to deep-link to; the assistant still
  //                                 names the camera in its reply)
  return path
    .replace(/^\/journeys(\/|$)/, "/journey$1")
    .replace(/^\/live\/[^/]+$/, "/live");
}

/** Human label for the tool currently running, for the activity line. */
export const TOOL_LABEL = {
  list_cameras: "Checking the registry",
  find_cameras_near: "Finding cameras",
  get_camera: "Looking up the camera",
  get_camera_health: "Reading health history",
  trace_vehicle: "Tracing the vehicle",
  search_plate: "Searching footage",
  list_sightings: "Fetching sightings",
  list_workers: "Checking workers",
  get_capacity: "Checking capacity",
  start_anpr: "Starting ANPR",
  stop_anpr: "Stopping ANPR",
  start_worker: "Starting the worker",
  stop_worker: "Stopping the worker",
  list_watchlist: "Reading the watchlist",
  add_to_watchlist: "Adding to the watchlist",
  list_alerts: "Fetching alerts",
  acknowledge_alert: "Acknowledging",
  resolve_alert: "Resolving",
  navigate_to: "Opening the page",
};
