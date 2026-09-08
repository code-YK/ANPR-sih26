import { useEffect } from "react";

// Every view names its own browser tab, so a judge (or an operator with ten
// tabs open) can tell which one is Alerts versus Journey without switching
// to it. Same "Sentinel" suffix everywhere -- see DESIGN.md §10 on keeping
// one word consistent across the console.
export function usePageTitle(title) {
  useEffect(() => {
    const previous = document.title;
    document.title = title ? `${title} · Sentinel` : "Sentinel · Operator Console";
    return () => {
      document.title = previous;
    };
  }, [title]);
}
