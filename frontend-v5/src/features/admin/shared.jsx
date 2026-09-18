import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { toast } from "../notifications/notificationStore.js";
import styles from "./Admin.module.css";

/** Run a mutation, refresh admin data, and report the outcome in one place. */
export function useAdminAction() {
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  const run = async (work, success, extraKeys = []) => {
    setBusy(true);
    try {
      const result = await work();
      await Promise.all([["admin"], ...extraKeys].map((queryKey) => queryClient.invalidateQueries({ queryKey })));
      if (success) toast(typeof success === "function" ? success(result) : success, { tone: "live" });
      return result ?? true;
    } catch (error) {
      toast("That didn't work", { tone: "critical", detail: error.message });
      return false;
    } finally {
      setBusy(false);
    }
  };
  return [run, busy];
}

export function initials(name) {
  return (name || "?")
    .split(/\s+/)
    .map((part) => part[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

export function Person({ name, email }) {
  return (
    <div className={styles.person}>
      <span className={styles.avatar} aria-hidden="true">
        {initials(name)}
      </span>
      <span className={styles.personText}>
        <span className={styles.personName}>{name}</span>
        <span className={styles.personEmail}>{email}</span>
      </span>
    </div>
  );
}

/** Section header row: title (+count) left, actions right, one line. */
export function SectionBar({ title, count, children }) {
  return (
    <div className={styles.sectionBar}>
      <h2 className={styles.sectionTitle}>
        {title}
        {count != null && <span className={styles.count}>{count}</span>}
      </h2>
      {children && <div className={styles.sectionActions}>{children}</div>}
    </div>
  );
}
