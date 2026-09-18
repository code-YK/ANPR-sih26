import { useCallback, useRef, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";

import { Button, Dialog } from "./ui.jsx";
import styles from "./Page.module.css";

export function Page({ children, narrow = false }) {
  return <div className={`${styles.page} ${narrow ? styles.narrow : ""}`}>{children}</div>;
}

export function PageHeader({ overline, title, description, actions, children }) {
  return (
    <header className={styles.header}>
      <div className={styles.headerText}>
        {overline && <p className="overline">{overline}</p>}
        <h1>{title}</h1>
        {description && <p className={styles.description}>{description}</p>}
      </div>
      {actions && <div className={styles.actions}>{actions}</div>}
      {children}
    </header>
  );
}

/** Route-backed tabs. `end` items match exactly. */
export function SubNav({ items, label }) {
  const { pathname } = useLocation();
  return (
    <nav className={`ui-segmented ${styles.subnav}`} aria-label={label}>
      {items.map((item) => {
        const active = item.end ? pathname === item.to || pathname === `${item.to}/` : pathname === item.to || pathname.startsWith(`${item.to}/`);
        return (
          <NavLink key={item.to} to={item.to} end={item.end} className="ui-segmented__item" aria-current={active ? "page" : undefined}>
            <span className="ui-segmented__label">
              {item.icon}
              {item.label}
              {item.count != null && <span className={styles.count}>{item.count}</span>}
            </span>
          </NavLink>
        );
      })}
    </nav>
  );
}

export function Toolbar({ children, label }) {
  return (
    <div className={styles.toolbar} role="toolbar" aria-label={label}>
      {children}
    </div>
  );
}

export function Section({ title, description, actions, children }) {
  return (
    <section className={styles.section}>
      {(title || actions) && (
        <div className={styles.sectionHeader}>
          <div>
            {title && <h2>{title}</h2>}
            {description && <p className={styles.description}>{description}</p>}
          </div>
          {actions && <div className={styles.actions}>{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

/**
 * `const [confirm, dialog] = useConfirm()`; render `dialog`, then
 * `if (await confirm({title, body, confirmLabel, danger})) ...`.
 */
export function useConfirm() {
  const [request, setRequest] = useState(null);
  const resolver = useRef(null);

  const confirm = useCallback(
    (options) =>
      new Promise((resolve) => {
        resolver.current = resolve;
        setRequest(options);
      }),
    [],
  );

  const settle = (value) => {
    resolver.current?.(value);
    resolver.current = null;
    setRequest(null);
  };

  const dialog = (
    <Dialog
      open={Boolean(request)}
      onClose={() => settle(false)}
      title={request?.title}
      footer={
        <>
          <Button variant="ghost" onClick={() => settle(false)}>
            Cancel
          </Button>
          <Button variant={request?.danger ? "danger-solid" : "primary"} onClick={() => settle(true)}>
            {request?.confirmLabel ?? "Confirm"}
          </Button>
        </>
      }
    >
      {request?.body && <p className="muted">{request.body}</p>}
    </Dialog>
  );

  return [confirm, dialog];
}
