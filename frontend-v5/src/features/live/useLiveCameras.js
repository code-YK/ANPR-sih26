import { useMemo } from "react";

import { useCameras, useModes } from "../../lib/queries.js";

/**
 * The cameras the Live screens show, curated for whichever demo mode is on.
 *
 * Government mode shows only real catalogue cameras (never an app-created
 * `manual-*` one) with the cameras it pointed at a recorded relay first;
 * demo mode shows only its own `manual-*` cameras. The registry, map and
 * status counts elsewhere always read the full, uncurated list -- this is a
 * presentation choice for the Live screens only.
 */
export function useLiveCameras() {
  const cameras = useCameras();
  const modes = useModes();
  const government = modes.data?.government;
  const demo = modes.data?.demo;

  const list = useMemo(() => {
    const all = cameras.data ?? [];
    const relayIds = new Set(government?.enabled ? government.camera_ids ?? [] : []);
    let result = all;
    if (demo?.enabled) result = result.filter((camera) => camera.camera_id.startsWith("manual-"));
    else if (government?.enabled) result = result.filter((camera) => !camera.camera_id.startsWith("manual-"));
    if (relayIds.size > 0) {
      result = [...result].sort((a, b) => (relayIds.has(a.camera_id) ? 0 : 1) - (relayIds.has(b.camera_id) ? 0 : 1));
    }
    return result;
  }, [cameras.data, government, demo]);

  return {
    cameras: list,
    allCameras: cameras.data ?? [],
    isLoading: cameras.isPending,
    error: cameras.error,
    governmentMode: government?.enabled ? government : null,
    demoMode: demo?.enabled ? demo : null,
  };
}

export function hasPreview(camera) {
  return Boolean(camera?.stream_available);
}
