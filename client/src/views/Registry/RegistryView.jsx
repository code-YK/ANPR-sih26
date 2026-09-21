import { NavLink, Route, Routes } from "react-router-dom";

import { usePageTitle } from "../../hooks/usePageTitle.js";
import CameraListView from "./CameraListView.jsx";
import GapAnalysisView from "./GapAnalysisView.jsx";
import HealthHistoryView from "./HealthHistoryView.jsx";
import MapView from "./MapView.jsx";

export default function RegistryView() {
  usePageTitle("Registry");

  return (
    <section className="registry-shell">
      <header className="registry-page-header">
        <div>
          <p className="registry-eyebrow">Estate</p>
          <h1>Registry</h1>
          <p className="registry-lead">Every onboarded camera, unfiltered by mode.</p>
        </div>
      </header>

      <nav className="registry-tabs" aria-label="Registry sections">
        <NavLink to="/registry" end className={({ isActive }) => (isActive ? "is-on" : undefined)}>
          Cameras
        </NavLink>
        <NavLink to="/registry/map" className={({ isActive }) => (isActive ? "is-on" : undefined)}>
          Map
        </NavLink>
        <NavLink
          to="/registry/gap-analysis"
          className={({ isActive }) => (isActive ? "is-on" : undefined)}
        >
          Coverage gaps
        </NavLink>
        <NavLink
          to="/registry/health-history"
          className={({ isActive }) => (isActive ? "is-on" : undefined)}
        >
          Health & maintenance
        </NavLink>
      </nav>

      <Routes>
        <Route index element={<CameraListView />} />
        <Route path="map" element={<MapView />} />
        <Route path="gap-analysis" element={<GapAnalysisView />} />
        <Route path="health-history" element={<HealthHistoryView />} />
      </Routes>
    </section>
  );
}
