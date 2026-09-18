import { QueryClient, useQuery } from "@tanstack/react-query";

import { api, isStatus } from "./api/client.js";

/**
 * Every authenticated request costs the backend several round trips to a
 * remote database, so polling is budgeted: each query polls only while its
 * screen is mounted, at the slowest cadence that still reads as live, and
 * returning to the window does not refetch everything at once (that burst
 * alone used to exhaust the backend's connection pool).
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (failureCount, error) => !isStatus(error, 401, 403, 404, 422) && failureCount < 2,
      refetchOnWindowFocus: false,
      refetchIntervalInBackground: false,
      staleTime: 3_000,
    },
  },
});

export const keys = {
  me: ["me"],
  cameras: ["cameras"],
  departments: ["departments"],
  modes: ["modes"],
  capacity: ["analytics", "capacity"],
  status: ["analytics", "status"],
  telemetry: (cameraId, backendMode) => ["telemetry", cameraId, backendMode],
  sightings: (cameraId) => ["sightings", cameraId],
  counts: (cameraId) => ["counts", cameraId],
  cameraAlerts: (cameraId) => ["alerts", "camera", cameraId],
  openAlerts: ["alerts", "open"],
  alerts: (status) => ["alerts", "list", status],
};

export const POLL = {
  telemetry: 1_500,
  statusFast: 2_000,
  status: 5_000,
  sightings: 3_000,
  openAlerts: 5_000,
  cameraAlerts: 5_000,
  counts: 15_000,
  modes: 30_000,
};

export function useCameras() {
  return useQuery({ queryKey: keys.cameras, queryFn: () => api("/cameras"), staleTime: 30_000 });
}

export function useDepartments() {
  return useQuery({ queryKey: keys.departments, queryFn: () => api("/departments"), staleTime: 5 * 60_000 });
}

/** Government and demo mode, read together (both are open to any user). */
export function useModes() {
  return useQuery({
    queryKey: keys.modes,
    queryFn: async () => {
      const [government, demo] = await Promise.all([
        api("/admin/government-mode").catch(() => null),
        api("/admin/demo-mode").catch(() => null),
      ]);
      return { government, demo };
    },
    refetchInterval: POLL.modes,
    staleTime: 20_000,
  });
}

export function useCapacity() {
  return useQuery({ queryKey: keys.capacity, queryFn: () => api("/analytics/capacity"), staleTime: Infinity });
}

/**
 * Every running or queued worker the backend reports, in one poll. Tightens
 * while this browser has a start or stop in flight so the transition lands
 * promptly, and relaxes otherwise.
 */
export function useAnalyticsStatus({ fast = false } = {}) {
  return useQuery({
    queryKey: keys.status,
    queryFn: () => api("/analytics/status"),
    refetchInterval: fast ? POLL.statusFast : POLL.status,
    refetchIntervalInBackground: true,
    staleTime: 1_000,
  });
}

export function useTelemetry(cameraId, backendMode, { enabled = true, interval = POLL.telemetry } = {}) {
  return useQuery({
    queryKey: keys.telemetry(cameraId, backendMode),
    queryFn: async () => {
      try {
        return await api(`/analytics/telemetry/${encodeURIComponent(cameraId)}?mode=${backendMode}`);
      } catch (error) {
        if (isStatus(error, 404)) return null; // no worker has published yet
        throw error;
      }
    },
    enabled: Boolean(enabled && cameraId && backendMode),
    refetchInterval: interval,
    staleTime: 0,
    retry: false,
  });
}

export function useCameraSightings(cameraId, { enabled = true, interval = POLL.sightings, limit = 40 } = {}) {
  return useQuery({
    queryKey: keys.sightings(cameraId),
    queryFn: () => api(`/sightings?camera_id=${encodeURIComponent(cameraId)}&limit=${limit}`),
    enabled: Boolean(enabled && cameraId),
    refetchInterval: interval,
  });
}

export function useCameraCounts(cameraId, { enabled = true } = {}) {
  return useQuery({
    queryKey: keys.counts(cameraId),
    queryFn: () => api(`/analytics/counts?camera_id=${encodeURIComponent(cameraId)}&limit=60`),
    enabled: Boolean(enabled && cameraId),
    refetchInterval: POLL.counts,
  });
}

export function useCameraAlerts(cameraId, { enabled = true } = {}) {
  return useQuery({
    queryKey: keys.cameraAlerts(cameraId),
    queryFn: () => api(`/alerts?camera_id=${encodeURIComponent(cameraId)}&limit=60`),
    enabled: Boolean(enabled && cameraId),
    refetchInterval: POLL.cameraAlerts,
  });
}

/** The console's heartbeat: open alerts, polled regardless of the view. */
export function useOpenAlerts({ enabled = true } = {}) {
  return useQuery({
    queryKey: keys.openAlerts,
    queryFn: () => api("/alerts?status=open&limit=200"),
    enabled,
    refetchInterval: POLL.openAlerts,
    refetchIntervalInBackground: true,
  });
}
