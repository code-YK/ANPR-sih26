import { Link } from "react-router-dom";

import { trackThumbUrl } from "../../api.js";
import { CertaintyMark } from "../../components/Badge.jsx";
import { useGsapReveal } from "../../hooks/useGsapReveal.js";

function fmtMs(ms) {
  const totalSec = Math.floor(ms / 1000);
  const mm = String(Math.floor(totalSec / 60)).padStart(2, "0");
  const ss = String(totalSec % 60).padStart(2, "0");
  return `${mm}:${ss}`;
}

function whenLabel(recording, track) {
  if (recording.recorded_at) {
    return new Date(new Date(recording.recorded_at).getTime() + track.first_ms).toLocaleString();
  }
  return `${fmtMs(track.first_ms)} into recording`;
}

function rankOf(hit, mode) {
  return mode === "person" ? hit.similarity : hit.track.best_conf;
}

// One card per recording that has at least one hit -- not one card per
// track -- because the operator's question is "which recordings show this
// vehicle/person", and a recording with three merged occurrences is one
// answer, not three.
//
// `mode` distinguishes the two search kinds this same layout serves:
// "plate" hits carry matched_plate/match_kind (exact vs pg_trgm fuzzy);
// "person" hits carry a cosine similarity against a generic appearance
// embedding (see PersonSearchHit's backend docstring for what that score
// does and does not mean) -- ranked candidates, not an asserted identity.
export default function ResultsGrid({ hits, query, mode = "plate" }) {
  // Before the empty-state return, not after it. Sitting below that branch
  // made this a conditionally-called hook: React saw a different hook count
  // on the render where the first results arrived, which is the "rendered
  // more hooks than during the previous render" crash, not a style nit.
  const gridRef = useGsapReveal(
    ".result-card",
    { stagger: 0.05, duration: 0.45, y: 20, scale: true },
    [hits.length],
  );

  if (hits.length === 0) {
    // DESIGN.md §7: state what was searched and the one action that fills
    // the screen, in the interface's own voice -- never a bare "no data".
    return (
      <p className="hint">
        {mode === "person"
          ? "No candidate matches for this photo. Only recordings with a finished person ingest run are searched -- check "
          : `No matches for ${query}. Only recordings with a finished vehicle ingest run are searched -- check `}
        <Link to="/investigate">Recordings</Link> for one still queued or running.
      </p>
    );
  }

  const byRecording = new Map();
  for (const hit of hits) {
    const key = hit.recording.id;
    if (!byRecording.has(key)) byRecording.set(key, { recording: hit.recording, hits: [] });
    byRecording.get(key).hits.push(hit);
  }
  const groups = [...byRecording.values()].sort(
    (a, b) => Math.max(...b.hits.map((h) => rankOf(h, mode))) - Math.max(...a.hits.map((h) => rankOf(h, mode))),
  );

  return (
    <div ref={gridRef} className="results-grid">
      {groups.map(({ recording, hits: recordingHits }) => {
        const best = recordingHits.reduce((a, b) => (rankOf(b, mode) > rankOf(a, mode) ? b : a));
        const occurrences = new Set(recordingHits.map((h) => h.track.occurrence_index)).size;
        return (
          <div key={recording.id} className="result-card">
            <Link to={`/investigate/recordings/${recording.id}?run=${best.track.run_id}&track=${best.track.track_ref}`}>
              {best.track.thumb_path ? (
                <img
                  src={trackThumbUrl(best.track.run_id, best.track.track_ref)}
                  alt=""
                  className="result-card-thumb"
                />
              ) : (
                <div className="result-card-thumb result-card-thumb-empty">no thumbnail</div>
              )}
            </Link>
            <div className="result-card-body">
              <Link to={`/investigate/recordings/${recording.id}?run=${best.track.run_id}&track=${best.track.track_ref}`}>
                {recording.original_filename}
              </Link>
              <p className="hint">
                {recording.department} · {occurrences} occurrence{occurrences === 1 ? "" : "s"}
              </p>
              <div className="result-card-chips">
                {recordingHits.map((h) => (
                  <Link
                    key={`${h.track.run_id}:${h.track.track_ref}`}
                    to={`/investigate/recordings/${recording.id}?run=${h.track.run_id}&track=${h.track.track_ref}`}
                    className="result-chip"
                    title={
                      mode === "person"
                        ? `${(h.similarity * 100).toFixed(0)}% appearance similarity -- ranked candidate, not a confirmed identity`
                        : `${h.match_kind} match, ${(h.track.best_conf * 100).toFixed(0)}% detection confidence`
                    }
                  >
                    {mode === "person" ? (
                      <CertaintyMark
                        state={h.similarity >= 0.7 ? "confirmed" : "inferred"}
                        value={`${whenLabel(recording, h.track)} · ${(h.similarity * 100).toFixed(0)}%`}
                        label="appearance match"
                      />
                    ) : (
                      // match_kind is how confident the SEARCH is that this
                      // track is the plate asked for -- exact string match vs
                      // pg_trgm fuzzy -- which is exactly the kind of thing
                      // DESIGN.md puts on the epistemic channel (texture),
                      // never colour. Distinct from the OCR's own
                      // confirmed/tentative read status, shown per-track in
                      // RecordingDetailView -- conflating the two would
                      // mislabel a fuzzy-matched but vote-confirmed
                      // plate as "inferred".
                      <CertaintyMark
                        state={h.match_kind === "exact" ? "confirmed" : "inferred"}
                        value={whenLabel(recording, h.track)}
                        label={h.match_kind === "exact" ? undefined : "fuzzy match"}
                      />
                    )}
                  </Link>
                ))}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
