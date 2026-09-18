import { Navigate, Route, Routes } from "react-router-dom";

import { Page, PageHeader, SubNav } from "../../components/Page.jsx";
import CameraListView from "./CameraListView.jsx";
import CameraMapView from "./CameraMapView.jsx";
import GapAnalysisView from "./GapAnalysisView.jsx";
import HealthView from "./HealthView.jsx";

export default function RegistryView() {
  return (
    <Page>
      <PageHeader
        overline="Estate"
        title="Registry"
        description="Every onboarded camera, unfiltered by mode."
      />
      <SubNav
        label="Registry sections"

        items={[
          { to: "/registry", label: "Cameras", end: true },
          { to: "/registry/map", label: "Map" },
          { to: "/registry/coverage", label: "Coverage gaps" },
          { to: "/registry/health", label: "Health & maintenance" },
        ]}
      />
      <Routes>
        <Route index element={<CameraListView />} />
        <Route path="map" element={<CameraMapView />} />
        <Route path="coverage" element={<GapAnalysisView />} />
        <Route path="health" element={<HealthView />} />
        <Route path="gap-analysis" element={<Navigate to="/registry/coverage" replace />} />
        <Route path="health-history" element={<Navigate to="/registry/health" replace />} />
        <Route path="*" element={<Navigate to="/registry" replace />} />
      </Routes>
    </Page>
  );
}
