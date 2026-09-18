import { describe, expect, it } from "vitest";

import {
  HEALTHY_RUN_MS,
  MISSING_POLLS_TO_FAIL,
  START_GRACE_MS,
  deriveWorkerView,
  reconcileEntries,
} from "./workerState.js";

const NOW = Date.parse("2026-09-17T10:00:00Z");
const id = "cam11::anpr";

function entry(patch) {
  return { id, cameraId: "cam11", mode: "anpr", phase: "starting", requestedAt: NOW, missingPolls: 0, ...patch };
}

function rows(...list) {
  return new Map(list.map((row) => [id, row]));
}

describe("reconcileEntries", () => {
  it("promotes a starting entry once the backend reports it running", () => {
    const started = new Date(NOW - 2_000).toISOString();
    const out = reconcileEntries({ [id]: entry() }, rows({ state: "running", started_at: started, pid: 7 }), NOW);
    expect(out[id]).toMatchObject({ phase: "running", backendStartedAt: started, pid: 7, seenRunning: false });
  });

  it("marks a worker as seen running only after a healthy run", () => {
    const started = new Date(NOW - HEALTHY_RUN_MS - 1).toISOString();
    const out = reconcileEntries({ [id]: entry() }, rows({ state: "running", started_at: started }), NOW);
    expect(out[id].seenRunning).toBe(true);
  });

  it("returns the same object when nothing changed", () => {
    const started = new Date(NOW - 60_000).toISOString();
    const entries = {
      [id]: entry({ phase: "running", backendStartedAt: started, seenRunning: true, missingPolls: 0, error: null }),
    };
    expect(reconcileEntries(entries, rows({ state: "running", started_at: started }), NOW)).toBe(entries);
  });

  it("never touches an entry with a request in flight", () => {
    const entries = { [id]: entry({ inFlight: true, requestedAt: NOW - 60_000 }) };
    expect(reconcileEntries(entries, new Map(), NOW)).toBe(entries);
  });

  it("keeps a starting entry through the grace period even when absent", () => {
    let entries = { [id]: entry({ requestedAt: NOW - 1_000 }) };
    for (let i = 0; i < MISSING_POLLS_TO_FAIL + 2; i += 1) entries = reconcileEntries(entries, new Map(), NOW);
    expect(entries[id].phase).toBe("starting");
  });

  it("fails a start that never appeared after the grace period", () => {
    let entries = { [id]: entry({ requestedAt: NOW - START_GRACE_MS - 1 }) };
    for (let i = 0; i < MISSING_POLLS_TO_FAIL; i += 1) entries = reconcileEntries(entries, new Map(), NOW);
    expect(entries[id].phase).toBe("failed");
  });

  it("does not declare a running worker gone on a single missed poll", () => {
    const entries = { [id]: entry({ phase: "running", seenRunning: true }) };
    const out = reconcileEntries(entries, new Map(), NOW);
    expect(out[id].phase).toBe("running");
    expect(out[id].missingPolls).toBe(1);
  });

  it("reports a healthy worker that vanished as ended, not failed", () => {
    let entries = { [id]: entry({ phase: "running", seenRunning: true, requestedAt: NOW - 600_000 }) };
    for (let i = 0; i < MISSING_POLLS_TO_FAIL; i += 1) entries = reconcileEntries(entries, new Map(), NOW);
    expect(entries[id].phase).toBe("ended");
  });

  it("removes a stopping entry once the backend no longer reports it", () => {
    const out = reconcileEntries({ [id]: entry({ phase: "stopping" }) }, new Map(), NOW);
    expect(out[id]).toBeUndefined();
  });

  it("keeps a stopping entry while the process is still listed", () => {
    const entries = { [id]: entry({ phase: "stopping" }) };
    expect(reconcileEntries(entries, rows({ state: "running", started_at: new Date(NOW).toISOString() }), NOW)).toBe(entries);
  });

  it("tracks queue position for a queued ANPR worker", () => {
    const out = reconcileEntries({ [id]: entry() }, rows({ state: "queued", queue_position: 2, last_error: null }), NOW);
    expect(out[id]).toMatchObject({ phase: "queued", queuePosition: 2 });
  });

  it("revives an ended entry the supervisor restarted", () => {
    const started = new Date(NOW - 1_000).toISOString();
    const out = reconcileEntries(
      { [id]: entry({ phase: "ended", error: "Stopped unexpectedly", seenRunning: true }) },
      rows({ state: "running", started_at: started }),
      NOW,
    );
    expect(out[id]).toMatchObject({ phase: "running", error: null });
  });
});

describe("deriveWorkerView", () => {
  const started = new Date(NOW - 10_000).toISOString();
  const running = { state: "running", started_at: started };

  it("is idle with nothing requested and nothing running", () => {
    expect(deriveWorkerView(null, null, undefined, NOW).state).toBe("idle");
  });

  it("is warming while no telemetry from this run exists", () => {
    expect(deriveWorkerView(null, running, null, NOW).state).toBe("warming");
  });

  it("ignores telemetry left over from an earlier run", () => {
    const stale = { updated_at: (NOW - 60_000) / 1000, fps: 20 };
    expect(deriveWorkerView(null, running, stale, NOW).state).toBe("warming");
  });

  it("is live with fresh telemetry, exposing fps and lag", () => {
    const fresh = { updated_at: (NOW - 500) / 1000, fps: 24.5, stream_lag_seconds: 1.8 };
    expect(deriveWorkerView(null, running, fresh, NOW)).toMatchObject({ state: "live", fps: 24.5, lag: 1.8, pulse: true });
  });

  it("is stalled when this run's telemetry stops advancing", () => {
    const longRunning = { state: "running", started_at: new Date(NOW - 120_000).toISOString() };
    const old = { updated_at: (NOW - 30_000) / 1000 };
    expect(deriveWorkerView(null, longRunning, old, NOW).state).toBe("stalled");
  });

  it("reports running without claiming liveness when telemetry is not watched", () => {
    expect(deriveWorkerView(null, running, undefined, NOW)).toMatchObject({ state: "running", tone: "live" });
  });

  it("prefers the stopping phase over the backend row", () => {
    expect(deriveWorkerView(entry({ phase: "stopping" }), running, undefined, NOW).state).toBe("stopping");
  });

  it("shows a failed start with its reason", () => {
    const view = deriveWorkerView(entry({ phase: "failed", error: "boom" }), null, undefined, NOW);
    expect(view).toMatchObject({ state: "failed", detail: "boom", tone: "critical" });
  });
});
