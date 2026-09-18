import { Download, RefreshCw } from "lucide-react";
import { useState } from "react";

import { Toolbar } from "../../components/Page.jsx";
import { Button } from "../../components/ui.jsx";
import { apiUrl } from "../../lib/api/media.js";
import { usePageTitle } from "../../lib/hooks.js";
import styles from "./Registry.module.css";

/** The backend renders this report; it's embedded so it prints and exports identically. */
export default function GapAnalysisView() {
  usePageTitle("Registry · Coverage gaps");
  const [nonce, setNonce] = useState(0);
  return (
    <>
      <Toolbar label="Report actions">
        <Button icon={<RefreshCw />} onClick={() => setNonce((value) => value + 1)}>
          Refresh report
        </Button>
        <a className="ui-btn ui-btn--secondary" href={apiUrl("/gap-analysis/export?format=pdf")} target="_blank" rel="noreferrer">
          <Download aria-hidden="true" />
          Download PDF
        </a>
      </Toolbar>
      <iframe className={styles.report} title="Coverage gap analysis" src={apiUrl(`/gap-analysis/export?format=html&_=${nonce}`)} />
    </>
  );
}
