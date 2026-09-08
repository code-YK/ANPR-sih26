import { createContext, useCallback, useContext, useRef, useState } from "react";

// Same single-toast, class-toggled pattern as the vanilla app's #toast
// element (style.css already has .toast/.toast.show) -- context-based here
// so any view or provider (AlertsContext included) can raise one without
// prop drilling.
const ToastCtx = createContext(null);

export function ToastProvider({ children }) {
  const [message, setMessage] = useState("");
  const [show, setShow] = useState(false);
  const timerRef = useRef(null);

  const showToast = useCallback((msg) => {
    setMessage(msg);
    setShow(true);
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => setShow(false), 2200);
  }, []);

  return (
    <ToastCtx.Provider value={showToast}>
      {children}
      <div className={show ? "toast show" : "toast"}>{message}</div>
    </ToastCtx.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastCtx);
  if (!ctx) throw new Error("useToast must be used within a ToastProvider");
  return ctx;
}
