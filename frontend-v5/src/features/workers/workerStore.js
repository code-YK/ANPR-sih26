import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

import { reconcileEntries } from "./workerState.js";

/**
 * The Workspace: AI inference workers this browser session asked for.
 *
 * Session-scoped by design (sessionStorage): it survives a reload of this tab
 * but not a new tab, and never touches the database. Each entry is reconciled
 * against GET /analytics/status on every poll -- see workerState.js.
 */
export const useWorkerStore = create(
  persist(
    (set) => ({
      entries: {},

      upsert: (id, patch) =>
        set((state) => {
          const current = state.entries[id];
          const base = current ?? { id, addedAt: Date.now(), missingPolls: 0, seenRunning: false };
          return { entries: { ...state.entries, [id]: { ...base, ...patch } } };
        }),

      remove: (id) =>
        set((state) => {
          if (!state.entries[id]) return state;
          const next = { ...state.entries };
          delete next[id];
          return { entries: next };
        }),

      reconcile: (rowsById, now) =>
        set((state) => {
          const next = reconcileEntries(state.entries, rowsById, now);
          return next === state.entries ? state : { entries: next };
        }),

      clear: () => set({ entries: {} }),
    }),
    {
      name: "sentinel.workspace",
      version: 1,
      storage: createJSONStorage(() => sessionStorage),
      partialize: (state) => ({ entries: state.entries }),
      // A request that was in flight when the page unloaded died with it.
      // Let the next status poll decide what is actually running.
      merge: (persisted, current) => {
        const entries = {};
        for (const [id, entry] of Object.entries(persisted?.entries ?? {})) {
          entries[id] = {
            ...entry,
            inFlight: false,
            missingPolls: 0,
            phase: entry.phase === "stopping" ? "running" : entry.phase,
          };
        }
        return { ...current, entries };
      },
    },
  ),
);

export function selectHasPending(state) {
  return Object.values(state.entries).some(
    (entry) => entry.inFlight || entry.phase === "starting" || entry.phase === "stopping" || entry.phase === "queued",
  );
}
