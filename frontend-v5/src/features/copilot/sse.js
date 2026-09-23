/**
 * Server-sent-event parsing for the Copilot stream.
 *
 * EventSource is GET-only, so the chat endpoint is a POST read through
 * fetch + ReadableStream instead. That means framing is ours to do: a
 * network chunk can split a `data:` line anywhere, including mid-UTF-8, so
 * the parser keeps a buffer and only emits whole frames.
 *
 * Kept free of React and fetch so it can be tested directly.
 */

/** Incremental `data:` frame parser. Feed it text, get back parsed events. */
export function createSseParser() {
  let buffer = "";

  return {
    /** @returns {object[]} events completed by this chunk */
    push(text) {
      buffer += text;
      const events = [];
      let separator;
      // Frames end at a blank line. Anything after the last one is a
      // partial frame and stays buffered for the next chunk.
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
 * Map a navigate_to tool result onto a router path.
 *
 * Only in-app absolute paths are allowed. `//host` is rejected explicitly:
 * it passes a naive "starts with /" check but browsers read it as
 * protocol-relative and would leave the console entirely. The path is
 * produced by our own backend, so this is defence in depth -- but this is
 * the one place where model-influenced output becomes navigation, which is
 * exactly where defence in depth belongs.
 */
export function navigationPath(result) {
  const path = result?.data?.path;
  if (typeof path !== "string") return null;
  if (!path.startsWith("/") || path.startsWith("//")) return null;
  return path;
}
