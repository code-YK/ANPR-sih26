import { create } from "zustand";

import { playSound } from "../../lib/audio/soundEngine.js";
import { useUiStore } from "../../lib/uiStore.js";
import { addNotification, shouldPlaySound, soundFor } from "./rules.js";

const lastPlayedAt = {};

export const useNotificationStore = create((set) => ({
  items: [],
  push: (input) => set((state) => ({ items: addNotification(state.items, input, Date.now()) })),
  dismiss: (id) => set((state) => ({ items: state.items.filter((item) => item.id !== id) })),
  clear: () => set({ items: [] }),
}));

/**
 * Raise a notification. `silent` suppresses sound; `quiet` records the event
 * for sound only (used when the camera's own sightings list is already on
 * screen and a card would cover it).
 */
export function notify(input, { silent = false, quiet = false } = {}) {
  if (!quiet) useNotificationStore.getState().push(input);
  if (silent) return;
  const sound = soundFor(input.kind);
  const now = Date.now();
  if (!sound || !useUiStore.getState().soundEnabled || !shouldPlaySound(sound, lastPlayedAt, now)) return;
  if (playSound(sound)) {
    lastPlayedAt[sound] = now;
  } else {
    useUiStore.getState().setSoundBlocked(true);
  }
}

/** Short feedback for an operator's own action. Never makes a sound. */
export function toast(title, { tone = "neutral", detail } = {}) {
  useNotificationStore.getState().push({ kind: "system", title, detail, tone });
}
