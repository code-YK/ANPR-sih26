import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";

// Native <dialog> instead of a div/.modal-backdrop pair (DESIGN.md §8): a
// focus trap, Esc-to-close, and a real backdrop come from the browser, none
// of which the old version had. Portaled to <body> so the app shell (#root)
// can be marked inert while this is open -- sealing off background scroll
// and screen-reader content -- without the inert also landing on the dialog
// itself, which would if it stayed a descendant of #root.
export default function Modal({ open, onClose, children, wide = false }) {
  const dialogRef = useRef(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  useEffect(() => {
    const root = document.getElementById("root");
    if (root) root.inert = open;
    return () => {
      if (root) root.inert = false;
    };
  }, [open]);

  // The dialog's own "close" event fires for every close path -- Esc, the
  // backdrop click below, or a caller-driven onClose -- so this is the one
  // place that needs to sync React state back, rather than duplicating the
  // sync in each trigger.
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return undefined;
    const handleClose = () => onClose();
    dialog.addEventListener("close", handleClose);
    return () => dialog.removeEventListener("close", handleClose);
  }, [onClose]);

  return createPortal(
    <dialog
      ref={dialogRef}
      className="modal"
      style={wide ? { width: 720 } : undefined}
      onClick={(e) => {
        // A click on ::backdrop bubbles with the dialog itself as target;
        // a click on any real child stops there. Same "click outside
        // closes" behaviour as the old backdrop div, no extra element.
        if (e.target === dialogRef.current) dialogRef.current.close();
      }}
    >
      {open && children}
    </dialog>,
    document.body,
  );
}
