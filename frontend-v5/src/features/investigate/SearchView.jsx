import { Car, ImageUp, Search, UserSearch } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { Toolbar } from "../../components/Page.jsx";
import { Badge, Button, Checkbox, EmptyState, Input, Notice, PlateChip, Segmented, Skeleton, Tooltip } from "../../components/ui.jsx";
import { api } from "../../lib/api/client.js";
import { trackThumbUrl } from "../../lib/api/media.js";
import { fmtPercent } from "../../lib/format.js";
import { usePageTitle } from "../../lib/hooks.js";
import { occurrenceTime } from "./RecordingDetailView.jsx";
import styles from "./Investigate.module.css";

function rank(hit, mode) {
  return mode === "person" ? hit.similarity : hit.track.best_conf;
}

function Results({ hits, mode, query }) {
  if (hits.length === 0) {
    return (
      <div className="ui-card">
        <EmptyState icon={mode === "person" ? <UserSearch /> : <Car />} title="No matches">
          {mode === "person" ? "No candidates for this photo." : `Nothing matched ${query}.`} Only recordings with a finished {mode === "person" ? "person" : "vehicle"} ingest run are searched.{" "}
          <Link to="/investigate" className="ui-link">
            Check recordings
          </Link>
        </EmptyState>
      </div>
    );
  }
  const groups = new Map();
  for (const hit of hits) {
    if (!groups.has(hit.recording.id)) groups.set(hit.recording.id, { recording: hit.recording, hits: [] });
    groups.get(hit.recording.id).hits.push(hit);
  }
  const sorted = [...groups.values()].sort((a, b) => Math.max(...b.hits.map((h) => rank(h, mode))) - Math.max(...a.hits.map((h) => rank(h, mode))));

  return (
    <div className={styles.results}>
      {sorted.map(({ recording, hits: list }) => {
        const best = list.reduce((a, b) => (rank(b, mode) > rank(a, mode) ? b : a));
        const link = (hit) => `/investigate/recordings/${recording.id}?run=${hit.track.run_id}&track=${hit.track.track_ref}`;
        return (
          <article key={recording.id} className={`ui-card ${styles.result}`}>
            <Link to={link(best)} className={styles.resultThumb}>
              {best.track.thumb_path ? <img src={trackThumbUrl(best.track.run_id, best.track.track_ref)} alt="" loading="lazy" /> : <span className="faint">No crop</span>}
            </Link>
            <div className={styles.resultBody}>
              <Link to={link(best)} className="ui-table__primary">
                {recording.original_filename}
              </Link>
              <span className="faint">
                {recording.department} · {new Set(list.map((hit) => hit.track.occurrence_index)).size} occurrence(s)
              </span>
              <div className={styles.chips}>
                {list.map((hit) => (
                  <Link key={`${hit.track.run_id}:${hit.track.track_ref}`} to={link(hit)} className={styles.chip}>
                    {mode === "person" ? (
                      <Tooltip content="Appearance similarity from a generic embedding — a ranked candidate, not a confirmed identity">
                        <span>
                          <Badge tone={hit.similarity >= 0.7 ? "signal" : undefined} outline={hit.similarity < 0.7}>
                            {fmtPercent(hit.similarity)}
                          </Badge>
                        </span>
                      </Tooltip>
                    ) : (
                      <>
                        <PlateChip plate={hit.matched_plate} />
                        {hit.match_kind !== "exact" && <Badge outline>fuzzy</Badge>}
                      </>
                    )}
                    <span className="data faint">{occurrenceTime(recording, hit.track)}</span>
                  </Link>
                ))}
              </div>
            </div>
          </article>
        );
      })}
    </div>
  );
}

function PlateSearch() {
  const [plate, setPlate] = useState("");
  const [fuzzy, setFuzzy] = useState(true);
  const [state, setState] = useState({ loading: false, hits: null, error: null, query: "" });

  async function submit(event) {
    event.preventDefault();
    const value = plate.trim();
    if (!value) return;
    setState((current) => ({ ...current, loading: true, error: null }));
    try {
      const hits = await api("/investigate/search/plate", { method: "POST", json: { plate: value, fuzzy, limit: 50 } });
      setState({ loading: false, hits, error: null, query: value });
    } catch (error) {
      setState({ loading: false, hits: null, error: error.message, query: value });
    }
  }

  return (
    <>
      <form onSubmit={submit}>
        <Toolbar label="Plate search">
          <div className="ui-search">
            <Search aria-hidden="true" />
            <Input value={plate} onChange={(e) => setPlate(e.target.value)} placeholder="GJ01AB1234" aria-label="Plate" />
          </div>
          <Checkbox label="Fuzzy match" checked={fuzzy} onChange={(e) => setFuzzy(e.target.checked)} />
          <Button type="submit" variant="primary" loading={state.loading}>
            Search
          </Button>
        </Toolbar>
      </form>
      {state.error && <Notice tone="critical">{state.error}</Notice>}
      {state.loading ? <Skeleton height={200} /> : state.hits ? <Results hits={state.hits} mode="plate" query={state.query} /> : (
        <p className="faint">Searches every recording you can see that has a finished vehicle ingest run.</p>
      )}
    </>
  );
}

function PersonSearch() {
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [state, setState] = useState({ loading: false, hits: null, error: null });

  useEffect(() => () => preview && URL.revokeObjectURL(preview), [preview]);

  async function submit(event) {
    event.preventDefault();
    if (!file) return;
    setState({ loading: true, hits: null, error: null });
    try {
      const body = new FormData();
      body.append("file", file);
      setState({ loading: false, hits: await api("/investigate/search/person", { method: "POST", body }), error: null });
    } catch (error) {
      setState({ loading: false, hits: null, error: error.message });
    }
  }

  return (
    <>
      <form onSubmit={submit} className={styles.personForm}>
        <label className={styles.drop} data-has-file={Boolean(file) || undefined}>
          {preview ? <img src={preview} alt="Query" className={styles.preview} /> : <ImageUp aria-hidden="true" />}
          <span>{file ? file.name : "Choose a photo of a person"}</span>
          <input
            type="file"
            accept="image/*"
            onChange={(e) => {
              const picked = e.target.files?.[0] ?? null;
              setFile(picked);
              setPreview(picked ? URL.createObjectURL(picked) : null);
              setState({ loading: false, hits: null, error: null });
            }}
          />
        </label>
        <Button type="submit" variant="primary" loading={state.loading} disabled={!file}>
          Find candidates
        </Button>
      </form>
      <p className="faint">Candidates are ranked by a generic appearance embedding. Review them — a high score is not a verified identity.</p>
      {state.error && <Notice tone="critical">{state.error}</Notice>}
      {state.loading ? <Skeleton height={200} /> : state.hits && <Results hits={state.hits} mode="person" />}
    </>
  );
}

export default function SearchView() {
  usePageTitle("Investigate · Search");
  const [mode, setMode] = useState("plate");
  return (
    <>
      <Segmented
        label="Search by"

        value={mode}
        onChange={setMode}
        options={[
          { value: "plate", label: "Plate", icon: <Car size={15} aria-hidden="true" /> },
          { value: "person", label: "Person photo", icon: <UserSearch size={15} aria-hidden="true" /> },
        ]}
        className={styles.modeSwitch}
      />
      {mode === "plate" ? <PlateSearch /> : <PersonSearch />}
    </>
  );
}
