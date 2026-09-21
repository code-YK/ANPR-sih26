import { useEffect } from "react";

export function usePageTitle(title) {
  useEffect(() => {
    const previous = document.title;
    document.title = title ? `${title} · CityTraceAI` : "CityTraceAI · Operator Console";
    return () => {
      document.title = previous;
    };
  }, [title]);
}
