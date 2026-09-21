import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";

import { api, trackThumbUrl } from "../../api.js";
import { usePolling } from "../../hooks/usePolling.js";
import { usePageTitle } from "../../hooks/usePageTitle.js";
import { canAccessDepartment, useAuth } from "../../context/AuthContext.jsx";
import { CertaintyMark } from "../../components/Badge.jsx";
import ImageLightbox from "../../components/ImageLightbox.jsx";
import { useToast } from "../../components/Toast.jsx";
import TrackOverlayPlayer from "./TrackOverlayPlayer.jsx";

const RUN_STATUS_LABEL = {
  queued: ["Queued", "badge-muted"],
  running: ["Running", "badge-warn"],
  completed: ["Completed", "badge-ok"],
  completed_partial: ["Completed (partial)", "badge-warn"],
  failed: ["Failed", "badge-bad"],
  stalled: ["Stalled", "badge-bad"],
  cancelled: ["Cancelled", "badge-muted"],
};

const ACTIVE_RUN_STATUSES = new Set(["queued", "running"]);

function fmtMs(ms) {
  const totalSec = Math.floor(ms / 1000);
  const mm = String(Math.floor(totalSec / 60)).padStart(2, "0");
  const ss = String(totalSec % 60).padStart(2, "0");
  return `${mm}:${ss}`;
}

function occurrenceLabel(recording, track) {
  if (recording?.recorded_at) {
    const t = new Date(new Date(recording.recorded_at).getTime() + track.first_ms);
    return t.toLocaleString();
  }
  return `${fmtMs(track.first_ms)} into recording`;
}

export default function RecordingDetailView() {
  const { id } = useParams();
  const [searchParams] = useSearchParams();
  const { user } = useAuth();
  const showToast = useToast();
  usePageTitle("Recording");

  const [recording, setRecording] = useState(null);
  const [runs, setRuns] = useState([]);
  const [selectedRunId, setSelectedRunId] = useState(null);
  const [tracks, setTracks] = useState([]);
  const [activeTrack, setActiveTrack] = useState(null);
  const [lightboxTrack, setLightboxTrack] = useState(null);
  const [kind, setKind] = useState("vehicle");
  const [imgsz, setImgsz] = useState("");
  const [busy, setBusy] = useState(false);

  const appliedUrlSelection = useRef(false);

  const refreshRecording = useCallback(async () => {
    setRecording(await api(`/investigate/recordings/${id}`));
  }, [id]);

  const refreshRuns = useCallback(async () => {
    const data = await api(`/investigate/recordings/${id}/runs`);
    setRuns(data);
    return data;
  }, [id]);

  useEffect(() => {
    refreshRecording().catch((e) => showToast(e.message));
  }, [refreshRecording]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    refreshRuns()
      .then((data) => {
        if (appliedUrlSelection.current || data.length === 0) return;
        const wanted = Number(searchParams.get("run"));
        const match = data.find((r) => r.id === wanted);
        setSelectedRunId((match || data[0]).id);
      })
      .catch((e) => showToast(e.message));
  }, [refreshRuns]); // eslint-disable-line react-hooks/exhaustive-deps

  const anyRunActive = runs.some((r) => ACTIVE_RUN_STATUSES.has(r.status));
  usePolling(refreshRuns, anyRunActive ? 3000 : 15000);

  const selectedRun = runs.find((r) => r.id === selectedRunId) || null;

  const refreshTracks = useCallback(async () => {
    if (!selectedRunId) {
      setTracks([]);
      return;
    }
    const data = await api(`/investigate/runs/${selectedRunId}/tracks`);
    setTracks(data);
    if (!appliedUrlSelection.current) {
      appliedUrlSelection.current = true;
      const wanted = Number(searchParams.get("track"));
      const match = data.find((t) => t.track_ref === wanted);
      if (match) {
        setActiveTrack(match);
      }
    }
  }, [selectedRunId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    refreshTracks().catch((e) => showToast(e.message));
  }, [refreshTracks]); // eslint-disable-line react-hooks/exhaustive-deps

  usePolling(refreshTracks, selectedRun && ACTIVE_RUN_STATUSES.has(selectedRun.status) ? 3000 : 15000, !!selectedRunId);

  const canOperate = recording && canAccessDepartment(user, recording.department, "operator");

  async function handleStartRun(e) {
    e.preventDefault();
    setBusy(true);
    try {
      const run = await api(`/investigate/recordings/${id}/runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind, imgsz: imgsz ? Number(imgsz) : null }),
      });
      showToast(`Ingest run #${run.id} queued`);
      appliedUrlSelection.current = true; // a fresh run shouldn't be clobbered by the URL's ?run=
      setSelectedRunId(run.id);
      await refreshRuns();
    } catch (err) {
      showToast("Could not start ingest: " + err.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleCancel(runId) {
    try {
      await api(`/investigate/runs/${runId}/cancel`, { method: "POST" });
      await refreshRuns();
    } catch (err) {
      showToast("Could not cancel: " + err.message);
    }
  }

  if (!recording) return <p className="hint">Loading…</p>;

  return (
    <>
      <div className="toolbar">
        <h2 style={{ margin: 0 }}>{recording.original_filename}</h2>
        <div className="spacer" />
        <span className="hint">{recording.department}</span>
      </div>

      {recording.status !== "ready" && (
        <p className="hint">
          This recording is {recording.status}
          {recording.reject_reason ? ` — ${recording.reject_reason}` : ""}.
          {recording.status === "normalising" && " Refresh once normalisation finishes to run ingest."}
        </p>
      )}

      {canOperate && recording.status === "ready" && (
        <form className="toolbar" onSubmit={handleStartRun}>
          <select value={kind} onChange={(e) => setKind(e.target.value)} disabled={busy}>
            <option value="vehicle">Vehicle (plate)</option>
            <option value="person">Person</option>
          </select>
          <select value={imgsz} onChange={(e) => setImgsz(e.target.value)} disabled={busy}>
            <option value="">960px (default)</option>
            <option value="640">640px (faster, lower recall on distant subjects)</option>
          </select>
          <button type="submit" className="primary" disabled={busy}>Run ingest</button>
        </form>
      )}

      {runs.length === 0 && <p className="hint">No ingest runs yet for this recording.</p>}

      {runs.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Run</th>
              <th>Kind</th>
              <th>Status</th>
              <th>Progress</th>
              <th>Tracks</th>
              <th>Started</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => {
              const [label, cls] = RUN_STATUS_LABEL[r.status] || [r.status, "badge-muted"];
              return (
                <tr
                  key={r.id}
                  className={r.id === selectedRunId ? "row-hover" : ""}
                  style={{ cursor: "pointer" }}
                  onClick={() => {
                    appliedUrlSelection.current = true;
                    setSelectedRunId(r.id);
                  }}
                >
                  <td>#{r.id}</td>
                  <td>{r.kind}</td>
                  <td>
                    <span className={`badge ${cls}`} title={r.error || undefined}>{label}</span>
                    {r.status === "queued" && r.queue_position != null && (
                      <span className="hint"> (position {r.queue_position})</span>
                    )}
                  </td>
                  <td>{r.progress_pct != null ? `${Math.round(r.progress_pct)}%` : "—"}</td>
                  <td>{r.track_count}</td>
                  <td>{r.started_at ? new Date(r.started_at).toLocaleTimeString() : "—"}</td>
                  <td>
                    {ACTIVE_RUN_STATUSES.has(r.status) && canOperate && (
                      <button
                        type="button"
                        className="secondary"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleCancel(r.id);
                        }}
                      >
                        Cancel
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {selectedRun && tracks.length > 0 && (
        <>
          <h3>Tracks — run #{selectedRun.id}</h3>
          <table>
            <thead>
              <tr>
                <th>Occurrence</th>
                <th>When</th>
                <th>Duration</th>
                <th>Plate</th>
                <th>Confidence</th>
                <th>Thumb</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {tracks.map((t) => (
                <tr key={t.track_ref}>
                  <td>{t.occurrence_index}</td>
                  <td>{occurrenceLabel(recording, t)}</td>
                  <td>{fmtMs(t.last_ms - t.first_ms)}</td>
                  <td>
                    {t.plate_confirmed ? (
                      <CertaintyMark state="confirmed" value={t.plate_confirmed} />
                    ) : t.plate_tentative ? (
                      // Tentative here means real: a corroborated read that
                      // didn't clear plates.py's zero-edit confirmation bar.
                      // The live pipeline never reports these at all (see
                      // DetectorView's own note), so this is the one place
                      // in the console a genuinely unconfirmed plate is
                      // shown -- the worker's own "?" suffix and the dashed
                      // treatment, exactly as DESIGN.md §5.1 describes.
                      <CertaintyMark
                        state="inferred"
                        value={`${t.plate_tentative}?`}
                        label="inferred"
                        title="Corroborated by more than one read, but at least one needed a character repair to fit the plate format -- not confirmed"
                      />
                    ) : (
                      <CertaintyMark state="unknown" label="not read" />
                    )}
                  </td>
                  <td>{(t.best_conf * 100).toFixed(0)}%</td>
                  <td>
                    {t.thumb_path ? (
                      <button
                        type="button"
                        className="thumb-btn"
                        onClick={() => setLightboxTrack(t)}
                        title="View this crop full-size"
                      >
                        <img
                          src={trackThumbUrl(t.run_id, t.track_ref)}
                          alt=""
                          className="track-thumb"
                        />
                      </button>
                    ) : (
                      <span className="hint">none</span>
                    )}
                  </td>
                  <td>
                    <button type="button" className="secondary" onClick={() => setActiveTrack(t)}>
                      View clip
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {activeTrack && (
        <TrackOverlayPlayer
          recordingId={recording.id}
          runId={activeTrack.run_id}
          trackRef={activeTrack.track_ref}
          firstMs={activeTrack.first_ms}
          label={`Occurrence ${activeTrack.occurrence_index} — ${occurrenceLabel(recording, activeTrack)}`}
        />
      )}

      <ImageLightbox
        src={lightboxTrack ? trackThumbUrl(lightboxTrack.run_id, lightboxTrack.track_ref) : null}
        filename={lightboxTrack ? `track-${lightboxTrack.track_ref}.jpg` : null}
        open={!!lightboxTrack}
        onClose={() => setLightboxTrack(null)}
      />
    </>
  );
}
