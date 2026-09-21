import { useState } from "react";
import { Image, Search as SearchIcon } from "lucide-react";

import { api } from "../../api.js";
import { usePageTitle } from "../../hooks/usePageTitle.js";
import ResultsGrid from "./ResultsGrid.jsx";

export default function SearchView() {
  usePageTitle("Investigate · Search");
  const [mode, setMode] = useState("plate");

  return (
    <div className="investigate-panel">
      <div className="investigate-mode-tabs" role="tablist" aria-label="Search mode">
        <button
          type="button"
          role="tab"
          aria-selected={mode === "plate"}
          className={mode === "plate" ? "is-on" : undefined}
          onClick={() => setMode("plate")}
        >
          <SearchIcon size={15} strokeWidth={2} />
          Plate
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === "person"}
          className={mode === "person" ? "is-on" : undefined}
          onClick={() => setMode("person")}
        >
          <Image size={15} strokeWidth={2} />
          Person photo
        </button>
      </div>
      {mode === "plate" ? <PlateSearch /> : <PersonSearch />}
    </div>
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
      setHits(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="investigate-search-block">
      <form className="investigate-search-form" onSubmit={onSearch}>
        <label className="investigate-field grow">
          <span>Registration mark</span>
          <input
            value={plate}
            onChange={(e) => setPlate(e.target.value.toUpperCase())}
            placeholder="e.g. GJ01AB1234"
            autoComplete="off"
            spellCheck={false}
          />
        </label>
        <label className="investigate-check">
          <input type="checkbox" checked={fuzzy} onChange={(e) => setFuzzy(e.target.checked)} />
          Fuzzy match
        </label>
        <button type="submit" className="primary investigate-search-btn" disabled={loading || !plate.trim()}>
          {loading ? "Searching…" : "Search"}
        </button>
      </form>

      {!hits && !error && (
        <p className="investigate-hint">
          Search finished vehicle ingest runs for exact or fuzzy plate matches. Only recordings you
          can access are included.
        </p>
      )}
      {error && <p className="investigate-error">Error: {error}</p>}
      {hits && <ResultsGrid hits={hits} query={searchedFor} mode="plate" />}
    </div>
  );
}

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
    <div className="investigate-search-block">
      <form className="investigate-search-form" onSubmit={onSearch}>
        <label className="investigate-field grow">
          <span>Query photo</span>
          <input type="file" accept="image/*" onChange={onFileChange} />
        </label>
        <button type="submit" className="primary investigate-search-btn" disabled={loading || !file}>
          {loading ? "Searching…" : "Search"}
        </button>
      </form>

      {previewUrl && (
        <img src={previewUrl} alt="query" className="investigate-preview" />
      )}

      {!hits && !error && (
        <p className="investigate-hint">
          Upload a photo to rank appearance-similar person tracks from finished person ingest runs.
          Scores are candidates for review — not verified identity matches.
        </p>
      )}
      {error && <p className="investigate-error">Error: {error}</p>}
      {hits && <ResultsGrid hits={hits} query="this photo" mode="person" />}
    </div>
  );
}
