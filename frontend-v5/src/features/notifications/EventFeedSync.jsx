import { useQueries } from "@tanstack/react-query";
import { useEffect, useMemo, useRef } from "react";
import { useShallow } from "zustand/react/shallow";

import { api } from "../../lib/api/client.js";
import { evidenceUrl } from "../../lib/api/media.js";
import { humanize } from "../../lib/format.js";
import { POLL, keys, useCameras, useOpenAlerts } from "../../lib/queries.js";
import { useUiStore } from "../../lib/uiStore.js";
import { isActivePhase } from "../workers/workerState.js";
import { useWorkerStore } from "../workers/workerStore.js";
import { notify } from "./notificationStore.js";

/**
 * Turns new backend events into notifications. There is no push channel, so
 * this reads the same polled queries the screens use (a camera's sightings
 * list and the open-alerts heartbeat) and diffs by id.
 *
 * - Plate sightings notify only for cameras with ANPR in this session's
 *   Workspace, and skip the card (not the sound) when that camera's
 *   sightings list is already on screen.
 * - Watchlist and suspicious alerts notify for every camera the operator can
 *   see, and replace the card of the sighting that raised them.
 * Whatever existed before a feed started is treated as already seen.
 */
export default function EventFeedSync() {
  const cameras = useCameras();
  const cameraNames = useMemo(
    () => new Map((cameras.data ?? []).map((camera) => [camera.camera_id, camera.name])),
    [cameras.data],
  );

  const anprCameraIds = useWorkerStore(
    useShallow((state) =>
      [...new Set(Object.values(state.entries).filter((entry) => entry.mode === "anpr" && isActivePhase(entry.phase)).map((entry) => entry.cameraId))].sort(),
    ),
  );

  const sightingQueries = useQueries({
    queries: anprCameraIds.map((cameraId) => ({
      queryKey: keys.sightings(cameraId),
      queryFn: () => api(`/sightings?camera_id=${encodeURIComponent(cameraId)}&limit=40`),
      refetchInterval: POLL.sightings,
      refetchIntervalInBackground: true,
    })),
  });

  const seenSightings = useRef(new Map());
  const sightingsVersion = sightingQueries.map((query) => query.dataUpdatedAt).join(",");

  useEffect(() => {
    const active = new Set(anprCameraIds);
    for (const cameraId of seenSightings.current.keys()) {
      if (!active.has(cameraId)) seenSightings.current.delete(cameraId);
    }
    anprCameraIds.forEach((cameraId, index) => {
      const query = sightingQueries[index];
      if (!query?.data) return;
      const seen = seenSightings.current.get(cameraId);
      if (!seen) {
        seenSightings.current.set(cameraId, new Set(query.data.map((row) => row.id)));
        return;
      }
      const fresh = query.data.filter((row) => !seen.has(row.id)).reverse();
      for (const sighting of fresh) {
        seen.add(sighting.id);
        const onScreen = Boolean(useUiStore.getState().visiblePanels[`${cameraId}::anpr`]);
        notify(
          {
            kind: "sighting",
            key: `sighting:${sighting.id}`,
            cameraId,
            cameraName: cameraNames.get(cameraId) ?? cameraId,
            plate: sighting.plate,
            detail: [humanize(sighting.vehicle_type), sighting.confidence != null ? sighting.confidence.toFixed(2) : null].filter(Boolean).join(" · "),
            time: sighting.seen_at,
            image: sighting.has_evidence ? evidenceUrl(sighting.id) : null,
            href: `/live/${encodeURIComponent(cameraId)}?ai=anpr`,
          },
          { quiet: onScreen },
        );
      }
    });
    // sightingQueries is a new array every render; its data version is what matters.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [anprCameraIds, cameraNames, sightingsVersion]);

  const openAlerts = useOpenAlerts();
  const seenAlerts = useRef(null);

  useEffect(() => {
    if (!openAlerts.data) return;
    if (seenAlerts.current === null) {
      seenAlerts.current = new Set(openAlerts.data.map((alert) => alert.id));
      return;
    }
    const fresh = openAlerts.data.filter((alert) => !seenAlerts.current.has(alert.id)).reverse();
    for (const alert of fresh) {
      seenAlerts.current.add(alert.id);
      const suspicious = alert.alert_type === "suspicious";
      notify({
        kind: suspicious ? "suspicious" : "watchlist",
        key: `alert:${alert.id}`,
        replaces: alert.sighting_id != null ? `sighting:${alert.sighting_id}` : undefined,
        cameraId: alert.camera_id,
        cameraName: alert.camera_name ?? cameraNames.get(alert.camera_id) ?? alert.camera_id,
        plate: alert.plate,
        title: suspicious ? alert.label ?? "Potentially dangerous person" : "Watchlist match",
        detail: suspicious
          ? `Severity ${alert.severity ?? "high"}${alert.match_confidence != null ? ` · ${alert.match_confidence.toFixed(2)}` : ""}`
          : [alert.reason_code && humanize(alert.reason_code), alert.severity && `${alert.severity} severity`].filter(Boolean).join(" · "),
        severity: alert.severity,
        time: alert.event_time,
        image: alert.has_evidence && alert.sighting_id != null ? evidenceUrl(alert.sighting_id) : null,
        href: `/live/${encodeURIComponent(alert.camera_id)}?ai=${suspicious ? "suspicious" : "anpr"}`,
      });
    }
  }, [openAlerts.data, cameraNames]);

  return null;
}
