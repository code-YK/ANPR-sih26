import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo } from "react";

import { api, isStatus } from "../../lib/api/client.js";
import { keys } from "../../lib/queries.js";

const AuthContext = createContext(null);

async function fetchMe() {
  try {
    return await api("/auth/me");
  } catch (error) {
    if (isStatus(error, 401)) return null;
    throw error;
  }
}

/**
 * Session state. /auth/me is re-read every minute and on focus so a grant
 * change (or a revoked session) reaches this UI without a reload; the API
 * remains the authorisation boundary either way.
 */
export function AuthProvider({ children, onSignedOut }) {
  const queryClient = useQueryClient();
  const me = useQuery({
    queryKey: keys.me,
    queryFn: fetchMe,
    refetchInterval: 60_000,
    staleTime: 30_000,
    refetchOnWindowFocus: true,
    retry: 1,
  });

  useEffect(() => {
    const handle = () => queryClient.setQueryData(keys.me, null);
    window.addEventListener("sentinel:unauthorised", handle);
    return () => window.removeEventListener("sentinel:unauthorised", handle);
  }, [queryClient]);

  const login = useCallback(
    async (email, password) => {
      const user = await api("/auth/login", { method: "POST", json: { email, password } });
      queryClient.setQueryData(keys.me, user);
      return user;
    },
    [queryClient],
  );

  const logout = useCallback(async () => {
    // Stop anything in flight first: a /auth/me response that left the server
    // before the session was deleted would otherwise land afterwards and
    // quietly sign the operator back in.
    await queryClient.cancelQueries();
    try {
      await api("/auth/logout", { method: "POST" });
    } catch {
      // Signed out locally regardless; the server session expires on its own.
    }
    onSignedOut?.();
    // Update the session query in place rather than clearing the cache first:
    // clear() detaches this provider's observer from the query, so the null
    // written afterwards never re-rendered it and the console stayed signed in.
    queryClient.setQueryData(keys.me, null);
    queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== keys.me[0] });
  }, [queryClient, onSignedOut]);

  const value = useMemo(
    () => ({
      user: me.data ?? null,
      loading: me.isPending,
      error: me.error,
      login,
      logout,
      refresh: me.refetch,
    }),
    [me.data, me.isPending, me.error, me.refetch, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
