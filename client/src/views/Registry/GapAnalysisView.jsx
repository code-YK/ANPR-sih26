import { useState } from "react";
import { Download, FileBarChart2, RefreshCw } from "lucide-react";

import { API } from "../../api.js";
import { usePageTitle } from "../../hooks/usePageTitle.js";

export default function GapAnalysisView() {
  usePageTitle("Registry · Gap analysis");
  const [nonce, setNonce] = useState(0);
  const [loading, setLoading] = useState(true);

  function refresh() {
    setLoading(true);
    setNonce((n) => n + 1);
  }

  return (
    <div className="gap-shell">
      <div className="gap-header">
        <div className="gap-header-copy">
          <p className="gap-eyebrow">
            <FileBarChart2 size={14} strokeWidth={2} />
            Coverage · Planning report
          </p>
          <h2>Gap analysis</h2>
          <p className="gap-lead">
            Network coverage summary for planning — departments, live share, ANPR viability, and
            placement gaps. Export PDF for briefing packs.
          </p>
        </div>
        <div className="gap-actions">
          <button type="button" className="secondary gap-btn" onClick={refresh}>
            <RefreshCw size={15} strokeWidth={2} />
            Refresh
          </button>
          <button
            type="button"
            className="primary gap-btn"
            onClick={() => window.open(`${API}/gap-analysis/export?format=pdf`, "_blank")}
          >
            <Download size={15} strokeWidth={2} />
            Download PDF
          </button>
        </div>
      </div>

      <div className={`gap-frame${loading ? " is-loading" : ""}`}>
        {loading && (
          <div className="gap-loading" aria-live="polite">
            <span className="gap-loading-pulse" />
            Loading report…
          </div>
        )}
        <iframe
          className="gap-embed"
          title="Gap analysis report"
          src={`${API}/gap-analysis/export?format=html&_=${nonce}`}
          onLoad={() => setLoading(false)}
        />
      </div>
    </div>
  );
}
