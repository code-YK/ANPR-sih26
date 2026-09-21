import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import { Film, Search, Shield } from "lucide-react";

import RecordingDetailView from "./RecordingDetailView.jsx";
import RecordingsView from "./RecordingsView.jsx";
import SearchView from "./SearchView.jsx";
import { usePageTitle } from "../../hooks/usePageTitle.js";

export default function InvestigateView() {
  usePageTitle("Investigate");
  const location = useLocation();
  const isDetail = location.pathname.includes("/recordings/");

  return (
    <section className="investigate-shell">
      {!isDetail && (
        <header className="investigate-hero">
          <div className="investigate-hero-copy">
            <p className="investigate-eyebrow">
              <Shield size={14} strokeWidth={2} />
              Operations · Evidence desk
            </p>
            <h1>Investigate</h1>
            <p className="investigate-lead">
              Upload recordings, run ingest, and search confirmed plate or appearance candidates
              across finished vehicle and person pipelines.
            </p>
          </div>
          <nav className="investigate-tabs" aria-label="Investigate sections">
            <NavLink to="/investigate" end className={({ isActive }) => (isActive ? "is-on" : undefined)}>
              <Film size={15} strokeWidth={2} />
              Recordings
            </NavLink>
            <NavLink
              to="/investigate/search"
              className={({ isActive }) => (isActive ? "is-on" : undefined)}
            >
              <Search size={15} strokeWidth={2} />
              Search
            </NavLink>
          </nav>
        </header>
      )}

      <Routes>
        <Route index element={<RecordingsView />} />
        <Route path="search" element={<SearchView />} />
        <Route path="recordings/:id" element={<RecordingDetailView />} />
      </Routes>
    </section>
  );
}
