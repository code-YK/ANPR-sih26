import { useState } from "react";

import { API } from "../../api.js";
import { usePageTitle } from "../../hooks/usePageTitle.js";

export default function GapAnalysisView() {
  usePageTitle("Registry · Gap analysis");
  const [nonce, setNonce] = useState(0);

  return (
    <>
      <div className="gap-actions">
        <button className="primary" onClick={() => setNonce((n) => n + 1)}>
          Refresh report
        </button>
        <button className="secondary" onClick={() => window.open(`${API}/gap-analysis/export?format=pdf`, "_blank")}>
          Download PDF
        </button>
      </div>
      <iframe
        className="gap-embed"
        title="Gap analysis report"
        src={`${API}/gap-analysis/export?format=html&_=${nonce}`}
      />
    </>
  );
}
