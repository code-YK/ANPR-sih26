import { useEffect, useRef } from "react";
import { Download } from "lucide-react";

import { API } from "../api.js";

const LABEL = { csv: "CSV", pdf: "PDF", html: "HTML report", json: "JSON" };

/**
 * Export links for a backend export endpoint that takes `?format=`.
 *
 * Every format is built by the backend from one builder (see sightings.py's
 * journey export), so the four can never disagree with each other or with
 * what the API returns. Plain links rather than fetch-and-blob: the browser
 * handles the download, the session cookie rides along, and HTML opens in a new
 * tab to read. A native <details> needs no open/close state; it closes itself
 * on an outside click below.
 */
export default function ExportMenu({ path, formats = ["csv", "pdf", "html", "json"], label = "Export" }) {
  const ref = useRef(null);

  useEffect(() => {
    function onDown(event) {
      if (ref.current?.open && !ref.current.contains(event.target)) ref.current.open = false;
    }
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, []);

  const join = path.includes("?") ? "&" : "?";
  return (
    <details className="export-menu" ref={ref}>
      <summary className="secondary export-menu-trigger">
        <Download size={15} strokeWidth={2} aria-hidden="true" />
        {label}
      </summary>
      <div className="export-menu-list" role="menu">
        {formats.map((format) => (
          <a
            key={format}
            role="menuitem"
            href={`${API}${path}${join}format=${format}`}
            target={format === "html" ? "_blank" : undefined}
            rel="noreferrer"
            onClick={() => {
              if (ref.current) ref.current.open = false;
            }}
          >
            {LABEL[format] ?? format.toUpperCase()}
          </a>
        ))}
      </div>
    </details>
  );
}
