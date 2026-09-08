import { useState } from "react";

import { api } from "../../api.js";
import { usePageTitle } from "../../hooks/usePageTitle.js";
import ResultsGrid from "./ResultsGrid.jsx";

export default function SearchView() {
  usePageTitle("Investigate search");
  const [mode, setMode] = useState("plate");

  return (
    <>
      <div className="toolbar" style={{ marginBottom: 12 }}>
        <button
          type="button"
          className={mode === "plate" ? "nav-btn active" : "nav-btn"}
          onClick={() => setMode("plate")}
        >
          Plate
        </button>
        <button
          type="button"
          className={mode === "person" ? "nav-btn active" : "nav-btn"}
          onClick={() => setMode("person")}
        >
          Person photo
        </button>
      </div>
      {mode === "plate" ? <PlateSearch /> : <PersonSearch />}
    </>
  );
}

function PlateSearch() {
  const [plate, setPlate] = useState("");
  const [fuzzy, setFuzzy] = useState(true);
  const [hits, setHits] = useState(null);
  const [searchedFor, setSearchedFor] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  async function onSearch(e) {
    e.preventDefault();
    const value = plate.trim();
    if (!value) return;
    setLoading(true);
    setError(null);
    try {
      setHits(
        await api("/investigate/search/plate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ plate: value, fuzzy, limit: 50 }),
        }),
      );
      setSearchedFor(value);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <form className="toolbar" onSubmit={onSearch}>
        <input
          placeholder="Search plate, e.g. GJ01AB1234"
          value={plate}
          onChange={(e) => setPlate(e.target.value)}
          style={{ maxWidth: 240 }}
        />
        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13 }}>
          <input type="checkbox" checked={fuzzy} onChange={(e) => setFuzzy(e.target.checked)} />
          Fuzzy match
        </label>
        <button type="submit" className="primary" disabled={loading}>
          {loading ? "Searching…" : "Search"}
        </button>
      </form>

      {!hits && <p className="hint">Search a plate across every recording you can see that has finished a vehicle ingest run.</p>}
      {error && <p className="hint">Error: {error}</p>}
      {hits && <ResultsGrid hits={hits} query={searchedFor} mode="plate" />}
    </>
  );
}

// Uploads a photo of a person and ranks every person track (from a
// finished person ingest run) by appearance similarity to it -- see
// PersonSearchHit's backend docstring for exactly what that similarity
// score does and does not claim. Reuses the same ResultsGrid the plate
// search uses, in "person" mode.
function PersonSearch() {
  const [file, setFile] = useState(null);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [hits, setHits] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  function onFileChange(e) {
    const picked = e.target.files[0] || null;
    setFile(picked);
    setHits(null);
    setError(null);
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(picked ? URL.createObjectURL(picked) : null);
  }

  async function onSearch(e) {
    e.preventDefault();
    if (!file) return;
    setLoading(true);
    setError(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      setHits(await api("/investigate/search/person", { method: "POST", body: fd }));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <form className="toolbar" onSubmit={onSearch}>
        <input type="file" accept="image/*" onChange={onFileChange} />
        <button type="submit" className="primary" disabled={loading || !file}>
          {loading ? "Searching…" : "Search"}
        </button>
      </form>

      {previewUrl && (
        <img
          src={previewUrl}
          alt="query"
          style={{ maxWidth: 160, maxHeight: 160, borderRadius: 6, border: "1px solid var(--border)", marginBottom: 12 }}
        />
      )}

      {!hits && !error && (
        <p className="hint">
          Upload a photo of a person to search for appearance-similar candidates across every recording you can
          see that has finished a person ingest run. This ranks candidates by a generic appearance embedding --
          it is not a verified identity match, and results should be reviewed, not taken as fact on their own.
        </p>
      )}
      {error && <p className="hint">Error: {error}</p>}
      {hits && <ResultsGrid hits={hits} query="this photo" mode="person" />}
    </>
  );
}
