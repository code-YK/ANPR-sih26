import { useEffect, useRef, useState } from "react";

/**
 * IntersectionObserver wrapper: returns [ref, isVisible]. Attach `ref` to the
 * element to watch. Used by CameraTile so a tile's player only mounts while
 * it's actually scrolled into view (LiveView combines this with the global
 * concurrency cap -- see LiveView.jsx).
 *
 * The default `rootMargin` extends a little past the viewport: a tile only
 * just off-screen still counts as visible, so scrolling down a row and back
 * up doesn't tear down a player that was fine a second ago and pay for a
 * fresh manifest fetch plus several seconds of re-buffering. Kept modest
 * (not the 800px this used to be) specifically so a 3-column grid of ~30
 * cameras doesn't pre-load most of the page's tiles at once on load --
 * bandwidth on this sandbox gateway is the actual constraint (GOV-ING-012),
 * so "loads as you scroll" needs to mean it, not prefetch everything within
 * a screen and a half. LiveView's sticky-active retention handles the rest.
 */
export function useVisibility(options = { threshold: 0.01, rootMargin: "150px 0px" }) {
  const ref = useRef(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    const observer = new IntersectionObserver(([entry]) => setVisible(entry.isIntersecting), options);
    observer.observe(el);
    return () => observer.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return [ref, visible];
}
