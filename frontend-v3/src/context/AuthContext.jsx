import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { api } from "../api.js";

const AuthCtx = createContext(null);

const RANK = { viewer: 1, operator: 2 };

// Slow on purpose: identity changes are rare, and focus/visibility events
// below catch the common case (an admin changes a grant while the operator
// is on another tab) far sooner than any interval would.
const SESSION_REFRESH_MS = 60000;

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      setUser(await api("/auth/me"));
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const unauthorised = () => setUser(null);
    window.addEventListener("sentinel:unauthorised", unauthorised);
    return () => window.removeEventListener("sentinel:unauthorised", unauthorised);
  }, [refresh]);

  // Re-read identity and grants periodically and whenever the tab regains
  // focus. The backend already re-reads grants on every request, so
  // *enforcement* was never stale -- but this client fetched /auth/me once
  // at mount and kept it forever, so an admin changing someone's clearance
  // (or disabling them) left that person's UI showing the old scope until
  // they happened to reload. It also surfaces a revoked or expired session
  // promptly instead of on their next write.
  useEffect(() => {
    const tick = () => {
      if (document.visibilityState === "visible") refresh();
    };
    const id = setInterval(tick, SESSION_REFRESH_MS);
    window.addEventListener("focus", tick);
    document.addEventListener("visibilitychange", tick);
    return () => {
      clearInterval(id);
      window.removeEventListener("focus", tick);
      document.removeEventListener("visibilitychange", tick);
    };
  }, [refresh]);

  const login = useCallback(async (email, password) => {
    const signedIn = await api("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    setUser(signedIn);
    return signedIn;
  }, []);

  const logout = useCallback(async () => {
    try {
      await api("/auth/logout", { method: "POST" });
    } finally {
      setUser(null);
    }
  }, []);

  const value = useMemo(() => ({ user, loading, login, logout, refresh }), [user, loading, login, logout, refresh]);
  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}

export function isSuperAdmin(user) {
  return user?.role === "super_admin";
}

export function isDepartmentAdmin(user) {
  return user?.role === "department_admin";
}

export function canAccessDepartment(user, department, clearance = "viewer") {
  if (!user) return false;
  // Super admins can access any camera, regardless of department assignment
  if (isSuperAdmin(user)) return true;
  if (!department) return false;
  const grant = user.grants?.find((item) => item.department === department);
  return Boolean(grant && RANK[grant.clearance] >= RANK[clearance]);
}
