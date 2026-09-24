import { useEffect, useMemo, useState } from "react";

import { api } from "../api.js";

/**
 * One poll of GET /analytics/status for the whole console.
 *
 * Five components wanted this list -- the top bar's AI chip, the status strip,
 * the Workspace dock, the Live wall's per-tile dots and the detector workbench
 * -- and each was polling it on its own timer. That is four wasted requests
 * every few seconds against an origin where the browser allows ~6 connections
 * and the detector's MJPEG stream, the HLS segments and every other poll are
 * already competing for them (see api.js for the measurements that forced the
 * dev-time origin split). It also meant the dock could show a worker the wall
 * had not noticed yet, because their timers were offset.
 *
 * So the poll lives here: one timer while anything is subscribed, one request,
 * one shared snapshot. Starting or stopping a worker calls refresh() and every
 * consumer updates together, instead of each waiting out its own interval.
 *
 * Identity is deliberately stable: when a poll returns the same rows as last
 * time -- the common case, since workers change rarely -- subscribers keep the
 * previous array and React re-renders nothing. Without that, every consumer of
 * this hook would re-render on a 4s heartbeat forever.
 */

const POLL_MS = 4000;

// `loaded` travels with the rows because an empty list before the first reply
// and an empty list after one mean different things: "we have not asked yet"
// and "nothing is running". A console that renders the first as a confident
// zero is the reason the status strip used to claim 0 workers while three were
// running, and the reason a camera with ANPR already running flashed its
// "start inference" card on every revisit.
let snapshot = { rows: [], loaded: false };
let signature = "";
let timer = null;
let refs = 0;
let inFlight = null;
const subscribers = new Set();

function publish(next) {
  const nextSignature = `${next.loaded}:${JSON.stringify(next.rows)}`;
  if (nextSignature === signature) return;
  signature = nextSignature;
  snapshot = next;
  for (const cb of subscribers) {
    try {
      cb(snapshot);
    } catch {
      // a bad subscriber must not stop the poll
    }
  }
}

async function poll() {
  if (inFlight) return inFlight;
  inFlight = (async () => {
    try {
      const data = await api("/analytics/status");
      publish({ rows: Array.isArray(data) ? data : [], loaded: true });
    } catch {
      // A failed poll keeps the last known rows: "we could not ask" is not
      // the same as "nothing is running", and blanking the dock on one bad
      // tick reads as workers dying.
    } finally {
      inFlight = null;
    }
  })();
  return inFlight;
}

/** Poll now rather than waiting for the next tick -- call after start/stop. */
export function refreshAnalyticsStatus() {
  return poll();
}

/** `{ rows, loaded }` for every worker the signed-in operator may see. */
export function useAnalyticsStatus() {
  const [current, setCurrent] = useState(snapshot);

  useEffect(() => {
    subscribers.add(setCurrent);
    setCurrent(snapshot);
    refs += 1;
    if (timer === null) {
      poll();
      timer = setInterval(poll, POLL_MS);
    }
    return () => {
      subscribers.delete(setCurrent);
      refs = Math.max(0, refs - 1);
      if (refs === 0 && timer !== null) {
        clearInterval(timer);
        timer = null;
      }
    };
  }, []);

  return current;
}

/** The same snapshot, narrowed to one camera. */
export function useCameraAnalyticsStatus(cameraId) {
  const { rows, loaded } = useAnalyticsStatus();
  const mine = useMemo(() => rows.filter((row) => row.camera_id === cameraId), [rows, cameraId]);
  return { rows: mine, loaded };
}

/** Worker states a console should treat as "this camera is busy right now". */
export const ACTIVE_STATES = ["running", "starting", "queued"];

export function isActiveState(state) {
  return ACTIVE_STATES.includes(state);
}

// The per-mode worker ceiling (GET /analytics/capacity). Server config, fixed
// for the backend process's lifetime, so it is fetched once and shared.
let capacityPromise = null;

export function useAnalyticsCapacity() {
  const [capacity, setCapacity] = useState(null);
  useEffect(() => {
    let cancelled = false;
    capacityPromise ??= api("/analytics/capacity").catch((error) => {
      capacityPromise = null; // let a later caller try again
      throw error;
    });
    capacityPromise.then((value) => !cancelled && setCapacity(value)).catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);
  return capacity;
}
