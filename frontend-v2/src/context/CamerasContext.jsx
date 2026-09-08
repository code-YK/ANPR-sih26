import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { api } from "../api.js";
import { useAuth } from "./AuthContext.jsx";

const CamerasCtx = createContext(null);

/**
 * Camera list, fetched once at app load and re-fetched on demand after a
 * mutation (create/edit/bulk-import/sync). Shared by Registry and, later,
 * Live -- both need the same list and neither should each run their own
 * polling loop for what is largely static data.
 */
export function CamerasProvider({ children }) {
  const [cameras, setCameras] = useState([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setCameras(await api("/cameras"));
    } finally {
      setLoading(false);
    }
  }, []);

  // GET /api/cameras is filtered by grant server-side, so this list is a
  // function of the caller's grants -- refetch whenever they actually
  // change. Keyed on a signature rather than the grants array itself
  // because AuthContext re-polls on an interval and hands back a fresh
  // array object each time, which would otherwise refetch every minute.
  const { user } = useAuth();
  const grantSignature = useMemo(
    () => (user?.grants ?? []).map((grant) => `${grant.department}:${grant.clearance}`).sort().join(","),
    [user],
  );

  useEffect(() => {
    refresh();
  }, [refresh, grantSignature]);

  return <CamerasCtx.Provider value={{ cameras, loading, refresh }}>{children}</CamerasCtx.Provider>;
}

export function useCameras() {
  const ctx = useContext(CamerasCtx);
  if (!ctx) throw new Error("useCameras must be used within a CamerasProvider");
  return ctx;
}
