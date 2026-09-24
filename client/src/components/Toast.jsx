import { createContext, useCallback, useContext } from "react";

import NotificationStack from "./NotificationStack.jsx";
import { toast } from "../lib/notifications.js";

/**
 * `useToast()` is the console's one call for "tell the operator what just
 * happened", used from about ninety places. It used to drive a single
 * one-line toast that the next message overwrote; it now raises a system card
 * in the notification stack (lib/notifications.js), so every existing call
 * gets the new presentation without being rewritten.
 *
 * Callers pass a bare string, so the tone is read from it: a message that
 * reports a failure is marked critical, one that reports a completed action
 * is marked as done, anything else is neutral.
 */
const ToastCtx = createContext(null);

const FAILURE = /\b(fail(ed|ure)?|error|denied|forbidden|required|can't|cannot|could not|blocked|invalid|unavailable)\b/i;
const DONE = /\b(started|stopped|saved|created|updated|deleted|added|removed|enabled|disabled|imported|exported|copied|sent|acknowledged|resolved|approved|rejected|dismissed)\b/i;

function toneOf(message) {
  if (FAILURE.test(message)) return "critical";
  if (DONE.test(message)) return "live";
  return "neutral";
}

export function ToastProvider({ children }) {
  const showToast = useCallback((message, options) => {
    const text = String(message ?? "");
    // "Start failed: 500: {...}" reads better as a title and a detail.
    const split = text.match(/^([^:]{3,60}):\s+(.+)$/s);
    toast(split ? split[1] : text, { tone: options?.tone ?? toneOf(text), detail: options?.detail ?? (split ? split[2] : undefined) });
  }, []);

  return (
    <ToastCtx.Provider value={showToast}>
      {children}
      <NotificationStack />
    </ToastCtx.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastCtx);
  if (!ctx) throw new Error("useToast must be used within a ToastProvider");
  return ctx;
}
