import { NavLink, Route, Routes } from "react-router-dom";

import CameraListView from "./CameraListView.jsx";
import HealthHistoryView from "./HealthHistoryView.jsx";
import MapView from "./MapView.jsx";
import GapAnalysisView from "./GapAnalysisView.jsx";

function subNavClass({ isActive }) {
  return isActive ? "nav-btn active" : "nav-btn";
}

// Absorbs Model 1's three views as nested routes so they stay reachable
// without three top-level nav slots -- same content, mechanically ported
// from the vanilla /legacy app, not redesigned.
export default function RegistryView() {
  return (
    <section className="view active">
      <nav className="toolbar" style={{ marginBottom: 16 }}>
        <NavLink to="/registry" end className={subNavClass}>
          Camera list
        </NavLink>
        <NavLink to="/registry/map" className={subNavClass}>
          GIS map
        </NavLink>
        <NavLink to="/registry/gap-analysis" className={subNavClass}>
          Gap analysis
        </NavLink>
        <NavLink to="/registry/health-history" className={subNavClass}>
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
