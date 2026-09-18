import { Download } from "lucide-react";
import { useEffect, useRef } from "react";

import { apiUrl } from "../../../lib/api/media.js";
import { useUiStore } from "../../../lib/uiStore.js";
import styles from "./Events.module.css";

/**
 * Marks an event list as on screen so notifications for the same camera and
 * mode are suppressed -- the list's own row highlight already says it.
 */
export function useRegisterPanel(key) {
  useEffect(() => {
    const { registerPanel, unregisterPanel } = useUiStore.getState();
    registerPanel(key);
    return () => unregisterPanel(key);
  }, [key]);
}

/**
 * Ids present when the list first rendered. Anything newer gets the arrival
 * highlight; the initial backlog never animates.
 */
export function useFreshIds(items, idOf = (item) => item.id) {
  const seen = useRef(null);
  if (seen.current === null && items) seen.current = new Set(items.map(idOf));
  const fresh = new Set();
  if (items && seen.current) {
    for (const item of items) {
      const id = idOf(item);
      if (!seen.current.has(id)) fresh.add(id);
    }
  }
  return fresh;
}

export function EventsHeader({ title, count, children }) {
  return (
    <div className={styles.header}>
      <h3>
        {title}
        {count != null && <span className={styles.count}>{count}</span>}
      </h3>
      <div className={styles.headerActions}>{children}</div>
    </div>
  );
}

export function ExportMenu({ path, formats = ["csv", "pdf", "html", "json"] }) {
  return (
    <details className={styles.menu}>
      <summary className="ui-btn ui-btn--ghost ui-btn--sm">
        <Download aria-hidden="true" />
        Export
      </summary>
      <div className={styles.menuList}>
        {formats.map((format) => (
          <a key={format} href={apiUrl(`${path}${path.includes("?") ? "&" : "?"}format=${format}`)} target={format === "html" ? "_blank" : undefined} rel="noreferrer">
            {format.toUpperCase()}
          </a>
        ))}
      </div>
    </details>
  );
}
