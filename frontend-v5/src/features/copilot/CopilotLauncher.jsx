import { Sparkles } from "lucide-react";
import { useQuery } from "@tanstack/react-query";

import { api } from "../../lib/api/client.js";
import { useUiStore } from "../../lib/uiStore.js";
import { useAuth } from "../auth/AuthProvider.jsx";
import styles from "./Copilot.module.css";

/**
 * The floating launcher, stacked directly above the Logs dock button.
 *
 * Hidden entirely when the server has no OPENROUTER_API_KEY: a button that
 * can only ever produce a 503 is worse than no button.
 */
export default function CopilotLauncher() {
  const { user } = useAuth();
  const open = useUiStore((state) => state.copilotOpen);
  const setOpen = useUiStore((state) => state.setCopilotOpen);

  // Keyed by user so signing in refetches: the first attempt can land before
  // the session cookie is established, and a cached failure with no refetch
  // would hide the launcher for the rest of the page's life.
  const status = useQuery({
    queryKey: ["copilot", "status", user?.id ?? null],
    queryFn: () => api("/copilot/status"),
    enabled: Boolean(user),
    staleTime: 5 * 60_000,
  });

  if (!status.data?.available) return null;

  return (
    <button
      type="button"
      className={styles.launcher}
      aria-label={open ? "Close Copilot" : "Open Copilot"}
      aria-expanded={open}
      data-open={open || undefined}
      onClick={() => setOpen(!open)}
    >
      <Sparkles size={17} aria-hidden="true" />
      <span>Copilot</span>
    </button>
  );
}
