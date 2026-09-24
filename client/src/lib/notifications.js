import { useEffect, useState } from "react";

/**
 * Operator notifications: the rules, the store, and the sound.
 *
 * A port of frontend-v5's notification system (rules.js + notificationStore.js),
 * kept dependency-free in this console's style -- a small module store with
 * subscribers, like lib/analyticsStatus.js, rather than zustand. The rules are
 * the same ones v5 settled on:
 *
 * - every kind has its own lifetime: a system acknowledgement is gone in four
 *   seconds, an alert stays for twelve;
 * - three cards at most, newest nearest the corner, the rest summarised as a
 *   "+N earlier" line with Clear all;
 * - an alert replaces the card of the sighting that raised it, and the same
 *   event never shows twice;
 * - a burst of sightings from one camera collapses into one "N new plates" card;
 * - sound is rate-limited per kind, so a burst makes one sound, not twenty.
 */

export const TTL_MS = {
  sighting: 6_500,
  "sighting-group": 8_000,
  watchlist: 12_000,
  suspicious: 12_000,
  worker: 9_000,
  system: 4_000,
};

export const MAX_VISIBLE = 3;
const MAX_ITEMS = 30;
const GROUP_THRESHOLD = 3;
const GROUP_WINDOW_MS = 5_000;
const SOUND_GAP_MS = { sighting: 3_000, alert: 1_500 };

let counter = 0;
function nextId(kind, now) {
  counter += 1;
  return `${kind}-${now}-${counter}`;
}

function sightingKeysOf(item) {
  return item.sightingKeys ?? (item.key ? [item.key] : []);
}

function trim(items) {
  return items.length > MAX_ITEMS ? items.slice(items.length - MAX_ITEMS) : items;
}

/** Pure: one notification added to `items`, newest last. */
export function addNotification(items, input, now) {
  const item = { id: nextId(input.kind, now), createdAt: now, ttl: TTL_MS[input.kind] ?? 6_000, count: 1, ...input };
  let next = items;

  if (item.replaces) {
    next = next
      .map((existing) => {
        if (existing.kind !== "sighting-group" || !existing.sightingKeys?.includes(item.replaces)) return existing;
        const sightingKeys = existing.sightingKeys.filter((key) => key !== item.replaces);
        return { ...existing, sightingKeys, count: Math.max(0, existing.count - 1) };
      })
      .filter((existing) => existing.key !== item.replaces && !(existing.kind === "sighting-group" && existing.count === 0));
  }

  if (item.key && next.some((existing) => existing.key === item.key || existing.sightingKeys?.includes(item.key))) {
    return next;
  }

  if (item.kind === "sighting") {
    const recent = next.filter(
      (existing) =>
        (existing.kind === "sighting" || existing.kind === "sighting-group") &&
        existing.cameraId === item.cameraId &&
        now - existing.createdAt < GROUP_WINDOW_MS,
    );
    const recentCount = recent.reduce((sum, existing) => sum + (existing.count || 1), 0);
    if (recent.length > 0 && recentCount + 1 >= GROUP_THRESHOLD) {
      const plates = [item.plate, ...recent.slice().reverse().flatMap((existing) => existing.plates ?? [existing.plate])]
        .filter(Boolean)
        .slice(0, 3);
      const group = {
        id: nextId("sighting-group", now),
        kind: "sighting-group",
        createdAt: now,
        ttl: TTL_MS["sighting-group"],
        cameraId: item.cameraId,
        cameraName: item.cameraName,
        href: item.href,
        time: item.time,
        count: recentCount + 1,
        plates,
        sightingKeys: [item.key, ...recent.flatMap(sightingKeysOf)].filter(Boolean),
      };
      next = next.filter((existing) => !recent.includes(existing));
      return trim([...next, group]);
    }
  }

  return trim([...next, item]);
}

/** Pure: the newest `max` are shown, the rest are counted. */
export function splitVisible(items, max = MAX_VISIBLE) {
  const visible = items.length > max ? items.slice(items.length - max) : items;
  return { visible, overflow: items.length - visible.length };
}

// -- store ---------------------------------------------------------------

let items = [];
const subscribers = new Set();

function setItems(next) {
  if (next === items) return;
  items = next;
  for (const cb of subscribers) {
    try {
      cb(items);
    } catch {
      // a bad subscriber must not stop the others
    }
  }
}

export function dismissNotification(id) {
  setItems(items.filter((item) => item.id !== id));
}

export function clearNotifications() {
  setItems([]);
}

export function useNotifications() {
  const [current, setCurrent] = useState(items);
  useEffect(() => {
    subscribers.add(setCurrent);
    setCurrent(items);
    return () => subscribers.delete(setCurrent);
  }, []);
  return current;
}

// -- sound -----------------------------------------------------------------

// One context for the page's lifetime. The previous alert beep built a new
// AudioContext per alert and never closed it; browsers cap how many can exist,
// so during an alert burst the sound quietly stopped working.
let audio = null;
const lastPlayedAt = {};
const soundListeners = new Set();
let soundBlocked = false;

// The operator's own mute, per browser. On by default: an alert that makes no
// sound on a control-room wall is easy to miss. Storage can be unavailable
// (private windows, blocked site data), in which case it simply stays on.
const SOUND_KEY = "sentinel-sound-enabled";
function readSoundPreference() {
  try {
    return window.localStorage.getItem(SOUND_KEY) !== "false";
  } catch {
    return true;
  }
}
let soundEnabled = typeof window !== "undefined" ? readSoundPreference() : true;
const enabledListeners = new Set();

export function setSoundEnabled(value) {
  soundEnabled = Boolean(value);
  try {
    window.localStorage.setItem(SOUND_KEY, String(soundEnabled));
  } catch {
    // not persisted; the choice still holds for this session
  }
  if (!soundEnabled) setSoundBlocked(false);
  for (const cb of enabledListeners) cb(soundEnabled);
}

export function useSoundEnabled() {
  const [enabled, setEnabled] = useState(soundEnabled);
  useEffect(() => {
    enabledListeners.add(setEnabled);
    setEnabled(soundEnabled);
    return () => enabledListeners.delete(setEnabled);
  }, []);
  return enabled;
}

function setSoundBlocked(value) {
  if (soundBlocked === value) return;
  soundBlocked = value;
  for (const cb of soundListeners) cb(value);
}

/** True while the browser's autoplay policy is holding sound back. */
export function useSoundBlocked() {
  const [blocked, setBlocked] = useState(soundBlocked);
  useEffect(() => {
    soundListeners.add(setBlocked);
    return () => soundListeners.delete(setBlocked);
  }, []);
  return blocked;
}

function soundFor(kind) {
  if (kind === "watchlist" || kind === "suspicious") return "alert";
  if (kind === "sighting" || kind === "sighting-group") return "sighting";
  return null;
}

function playTone(sound) {
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return false;
    audio ??= new AudioCtx();
    if (audio.state === "suspended") {
      audio.resume().catch(() => {});
      // Resuming needs a user gesture under autoplay rules; until one has
      // happened this stays suspended and the stack says so.
      if (audio.state === "suspended") return false;
    }
    const now = audio.currentTime;
    // An alert is two short high notes; a sighting one soft lower one -- the
    // two must be told apart without looking.
    const notes = sound === "alert" ? [[880, 0], [1175, 0.16]] : [[660, 0]];
    for (const [frequency, offset] of notes) {
      const osc = audio.createOscillator();
      const gain = audio.createGain();
      osc.frequency.value = frequency;
      gain.gain.setValueAtTime(sound === "alert" ? 0.18 : 0.08, now + offset);
      gain.gain.exponentialRampToValueAtTime(0.001, now + offset + 0.14);
      osc.connect(gain);
      gain.connect(audio.destination);
      osc.start(now + offset);
      osc.stop(now + offset + 0.15);
    }
    return true;
  } catch {
    return false;
  }
}

if (typeof window !== "undefined") {
  // The first interaction anywhere unlocks audio for the rest of the session.
  window.addEventListener(
    "pointerdown",
    () => {
      audio?.resume?.().catch(() => {});
      setSoundBlocked(false);
    },
    { capture: true },
  );
}

// -- raising notifications -------------------------------------------------

/**
 * Raise a notification. `silent` suppresses sound; `quiet` plays the sound but
 * shows no card (the event is already on screen, e.g. that camera's own rail).
 */
export function notify(input, { silent = false, quiet = false } = {}) {
  const now = Date.now();
  if (!quiet) setItems(addNotification(items, input, now));
  if (silent || !soundEnabled) return;
  const sound = soundFor(input.kind);
  if (!sound) return;
  const last = lastPlayedAt[sound];
  if (last != null && now - last < SOUND_GAP_MS[sound]) return;
  if (playTone(sound)) {
    lastPlayedAt[sound] = now;
    setSoundBlocked(false);
  } else {
    setSoundBlocked(true);
  }
}

/**
 * Short feedback for the operator's own action. Never makes a sound. `tone`
 * is "neutral", "live" (it worked) or "critical" (it did not).
 */
export function toast(title, { tone = "neutral", detail } = {}) {
  setItems(addNotification(items, { kind: "system", title, detail, tone }, Date.now()));
}
