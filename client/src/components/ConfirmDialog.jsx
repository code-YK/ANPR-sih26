import { useCallback, useRef, useState } from "react";

import Modal from "./Modal.jsx";

/**
 * A confirmation that looks like the rest of the console, as a promise:
 *
 *   const [confirm, confirmDialog] = useConfirm();
 *   if (!(await confirm({ title, body, confirmLabel, danger: true }))) return;
 *   ...
 *   return <>{...}{confirmDialog}</>;
 *
 * Replaces window.confirm, whose native dialog ignores the theme, cannot say
 * what will happen in more than one line, and blocks the page's own timers --
 * the alert poll and the live wall freeze for as long as it is open. Built on
 * Modal, so it gets the native <dialog> focus trap and Esc-to-cancel.
 */
export function useConfirm() {
  const [request, setRequest] = useState(null);
  const resolver = useRef(null);

  const settle = useCallback((value) => {
    resolver.current?.(value);
    resolver.current = null;
    setRequest(null);
  }, []);

  const confirm = useCallback((options) => {
    resolver.current?.(false);
    return new Promise((resolve) => {
      resolver.current = resolve;
      setRequest(options);
    });
  }, []);

  const dialog = (
    <Modal open={Boolean(request)} onClose={() => settle(false)}>
      {request && (
        <div className="confirm-dialog">
          <h2>{request.title}</h2>
          {request.body && <p className="confirm-dialog-body">{request.body}</p>}
          <div className="actions">
            <button type="button" className="secondary" onClick={() => settle(false)}>
              {request.cancelLabel ?? "Cancel"}
            </button>
            <button
              type="button"
              className={request.danger ? "primary confirm-danger" : "primary"}
              onClick={() => settle(true)}
              autoFocus
            >
              {request.confirmLabel ?? "Confirm"}
            </button>
          </div>
        </div>
      )}
    </Modal>
  );

  return [confirm, dialog];
}
