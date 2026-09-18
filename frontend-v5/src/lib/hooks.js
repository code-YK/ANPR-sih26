import { useEffect, useRef, useState } from "react";

/** A clock that re-renders its caller every `intervalMs` (0 disables). */
export function useNow(intervalMs = 1_000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!intervalMs) return undefined;
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

export function usePageTitle(title) {
  useEffect(() => {
    document.title = title ? `${title} · Sentinel` : "Sentinel";
  }, [title]);
}

export function useDocumentVisible() {
  const [visible, setVisible] = useState(() => document.visibilityState === "visible");
  useEffect(() => {
    const handle = () => setVisible(document.visibilityState === "visible");
    document.addEventListener("visibilitychange", handle);
    return () => document.removeEventListener("visibilitychange", handle);
  }, []);
  return visible;
}

/** Latest value in a ref, for callbacks that must not re-subscribe. */
export function useLatest(value) {
  const ref = useRef(value);
  ref.current = value;
  return ref;
}

export function useMediaQuery(query) {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const list = window.matchMedia(query);
    const handle = () => setMatches(list.matches);
    handle();
    list.addEventListener("change", handle);
    return () => list.removeEventListener("change", handle);
  }, [query]);
  return matches;
}
