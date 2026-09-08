import { NavLink, Route, Routes } from "react-router-dom";

import RecordingDetailView from "./RecordingDetailView.jsx";
import RecordingsView from "./RecordingsView.jsx";
import SearchView from "./SearchView.jsx";

function subNavClass({ isActive }) {
  return isActive ? "nav-btn active" : "nav-btn";
}

// Backend-only feature as of this build -- see docs/investigate-testing.md.
// Vehicle/plate search only; person/embedding search is a later phase.
export default function InvestigateView() {
  return (
    <section className="view active">
      <nav className="toolbar" style={{ marginBottom: 16 }}>
        <NavLink to="/investigate" end className={subNavClass}>
          Recordings
        </NavLink>
        <NavLink to="/investigate/search" className={subNavClass}>
          Search
        </NavLink>
      </nav>
      <Routes>
        <Route index element={<RecordingsView />} />
        <Route path="search" element={<SearchView />} />
        <Route path="recordings/:id" element={<RecordingDetailView />} />
      </Routes>
    </section>
  );
}
