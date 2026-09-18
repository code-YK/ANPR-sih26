import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

/**
 * View state that isn't server data. Viewer conveniences (sound, grid density,
 * preview limit) persist in localStorage; everything else is per page load.
 */
export const useUiStore = create(
  persist(
    (set) => ({
      soundEnabled: true,
      soundBlocked: false,
      gridColumns: 3,
      previewLimit: 9,
      workspaceOpen: false,
      logsOpen: false,
      logsTab: "be",
      /** Camera whose inference sheet is open, or null. */
      sheetCameraId: null,
      /** cameraId -> mode key selected in its inference tabs. */
      activeTab: {},
      /** "cameraId::mode" -> number of mounted event panels showing it. */
      visiblePanels: {},
      /** Id of the Workspace entry that was just added, for the rail callout. */
      recentlyAdded: null,

      setSoundEnabled: (soundEnabled) => set({ soundEnabled }),
      setSoundBlocked: (soundBlocked) => set({ soundBlocked }),
      setGridColumns: (gridColumns) => set({ gridColumns }),
      setPreviewLimit: (previewLimit) => set({ previewLimit }),
      setWorkspaceOpen: (workspaceOpen) => set({ workspaceOpen }),
      setLogsOpen: (logsOpen) => set({ logsOpen }),
      openLogs: (logsTab) => set({ logsOpen: true, logsTab }),
      setLogsTab: (logsTab) => set({ logsTab }),
      openSheet: (cameraId) => set({ sheetCameraId: cameraId }),
      closeSheet: () => set({ sheetCameraId: null }),
      setActiveTab: (cameraId, mode) => set((state) => ({ activeTab: { ...state.activeTab, [cameraId]: mode } })),
      flagRecentlyAdded: (id) => set({ recentlyAdded: { id, at: Date.now() } }),
      registerPanel: (key) =>
        set((state) => ({ visiblePanels: { ...state.visiblePanels, [key]: (state.visiblePanels[key] ?? 0) + 1 } })),
      unregisterPanel: (key) =>
        set((state) => {
          const count = (state.visiblePanels[key] ?? 1) - 1;
          const visiblePanels = { ...state.visiblePanels };
          if (count <= 0) delete visiblePanels[key];
          else visiblePanels[key] = count;
          return { visiblePanels };
        }),
    }),
    {
      name: "sentinel.ui",
      version: 1,
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        soundEnabled: state.soundEnabled,
        gridColumns: state.gridColumns,
        previewLimit: state.previewLimit,
      }),
    },
  ),
);
