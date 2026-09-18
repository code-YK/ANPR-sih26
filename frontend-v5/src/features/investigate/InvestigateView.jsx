import { Navigate, Route, Routes } from "react-router-dom";

import { Page, PageHeader, SubNav } from "../../components/Page.jsx";
import RecordingDetailView from "./RecordingDetailView.jsx";
import RecordingsView from "./RecordingsView.jsx";
import SearchView from "./SearchView.jsx";

export default function InvestigateView() {
  return (
    <Page>
      <PageHeader
        overline="Forensics"
        title="Investigate"
        description="Upload footage, then search it by plate or person."
      />
      <SubNav
        label="Investigate sections"

        items={[
          { to: "/investigate", label: "Recordings", end: true },
          { to: "/investigate/search", label: "Search" },
        ]}
      />
      <Routes>
        <Route index element={<RecordingsView />} />
        <Route path="search" element={<SearchView />} />
        <Route path="recordings/:id" element={<RecordingDetailView />} />
        <Route path="*" element={<Navigate to="/investigate" replace />} />
      </Routes>
    </Page>
  );
}
