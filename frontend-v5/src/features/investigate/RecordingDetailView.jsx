import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Play, ScanSearch, Search, X } from "lucide-react";
import { memo, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { Section, Toolbar } from "../../components/Page.jsx";
import { Badge, Button, Checkbox, Dialog, EmptyState, IconButton, Input, Notice, PlateChip, Select, Skeleton, Tooltip } from "../../components/ui.jsx";
import { api } from "../../lib/api/client.js";
import { trackThumbUrl } from "../../lib/api/media.js";
import { fmtDateTime, fmtDuration, fmtPercent } from "../../lib/format.js";
import { usePageTitle } from "../../lib/hooks.js";
import { canAccessDepartment } from "../../lib/permissions.js";
import { useAuth } from "../auth/AuthProvider.jsx";
import { toast } from "../notifications/notificationStore.js";
import TrackOverlayPlayer from "./TrackOverlayPlayer.jsx";
import styles from "./Investigate.module.css";

const RUN_STATUS = {
  queued: ["Queued", "pending"],
  running: ["Running", "signal"],
  completed: ["Completed", "live"],
  completed_partial: ["Partial", "pending"],
  failed: ["Failed", "critical"],
  stalled: ["Stalled", "critical"],
  cancelled: ["Cancelled"],
};
const ACTIVE = new Set(["queued", "running"]);

export function occurrenceTime(recording, track) {
  if (recording?.recorded_at) return fmtDateTime(new Date(new Date(recording.recorded_at).getTime() + track.first_ms));
  return `${fmtDuration(track.first_ms / 1000)} into the file`;
}

const PAGE_SIZE = 48;

/**
 * Memoised and paginated: a vehicle run can hold hundreds of tracks, and the
 * page polls its runs while an ingest is active. Rendering (and requesting a
 * thumbnail for) every track on every poll made the page crawl.
 */
const TrackGrid = memo(function TrackGrid({ tracks, recording, activeRef, onPlay, onZoom }) {
  const [limit, setLimit] = useState(PAGE_SIZE);
  const [filter, setFilter] = useState("");
  const [platesOnly, setPlatesOnly] = useState(false);
  const needle = filter.trim().toUpperCase().replace(/\s+/g, "");
  const filtered = tracks.filter((track) => {
    const plate = track.plate_confirmed ?? track.plate_tentative ?? "";
    if (platesOnly && !plate) return false;
    return !needle || plate.includes(needle);
  });
  const shown = filtered.slice(0, limit);
  const hasPlates = tracks.some((track) => track.plate_confirmed || track.plate_tentative);

  return (
    <>
      {hasPlates && (
        <Toolbar label="Track filters">
          <div className="ui-search">
            <Search aria-hidden="true" />
            <Input type="search" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter by plate" aria-label="Filter tracks by plate" />
          </div>
          <Checkbox label="Read plates only" checked={platesOnly} onChange={(e) => setPlatesOnly(e.target.checked)} />
          <span className="faint tabular">
            {filtered.length} of {tracks.length}
          </span>
        </Toolbar>
      )}
      <div className={styles.trackGrid}>
        {shown.map((track) => (
          <article key={`${track.run_id}-${track.track_ref}`} className={`ui-card ${styles.track}`} data-active={activeRef === track.track_ref || undefined}>
            <button type="button" className={styles.trackThumb} onClick={() => track.thumb_path && onZoom(track)} disabled={!track.thumb_path} aria-label="View crop">
              {track.thumb_path ? <img src={trackThumbUrl(track.run_id, track.track_ref)} alt="" loading="lazy" decoding="async" /> : <span className="faint">No crop</span>}
            </button>
            <div className={styles.trackBody}>
              <div className={styles.trackTop}>
                <span className="overline">#{track.occurrence_index}</span>
                <span className="data faint">{fmtPercent(track.best_conf)}</span>
              </div>
              {track.plate_confirmed ? (
                <PlateChip plate={track.plate_confirmed} />
              ) : track.plate_tentative ? (
                <PlateChip plate={`${track.plate_tentative}?`} title="Corroborated but needed a character repair to fit the plate format — not confirmed" />
              ) : (
                <span className="faint">{track.kind === "person" ? "Person" : "Plate not read"}</span>
              )}
              <span className={styles.trackMeta}>
                {occurrenceTime(recording, track)} · {fmtDuration((track.last_ms - track.first_ms) / 1000)}
              </span>
              <Button size="sm" variant="secondary" icon={<Play />} onClick={() => onPlay(track)}>
                Play
              </Button>
            </div>
          </article>
        ))}
      </div>
      {filtered.length > limit && (
        <div className={styles.more}>
          <Button onClick={() => setLimit((value) => value + PAGE_SIZE)}>Show {Math.min(PAGE_SIZE, filtered.length - limit)} more</Button>
        </div>
      )}
    </>
  );
});

export default function RecordingDetailView() {
  const { id } = useParams();
  const [searchParams] = useSearchParams();
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [runId, setRunId] = useState(Number(searchParams.get("run")) || null);
  const [activeTrack, setActiveTrack] = useState(null);
  const [lightbox, setLightbox] = useState(null);
  const playerRef = useRef(null);

  // Bring the player into view when a track is chosen from further down the page.
  useEffect(() => {
    if (activeTrack) playerRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [activeTrack]);
  const [kind, setKind] = useState("vehicle");
  const [imgsz, setImgsz] = useState("");
  const [starting, setStarting] = useState(false);

  const recording = useQuery({ queryKey: ["recording", id], queryFn: () => api(`/investigate/recordings/${id}`) });
  usePageTitle(recording.data?.original_filename ?? "Recording");

  const runs = useQuery({
    queryKey: ["runs", id],
    queryFn: () => api(`/investigate/recordings/${id}/runs`),
    refetchInterval: (query) => ((query.state.data ?? []).some((run) => ACTIVE.has(run.status)) ? 3_000 : 15_000),
  });

  useEffect(() => {
    if (!runId && runs.data?.length) setRunId(runs.data[0].id);
  }, [runs.data, runId]);

  const selectedRun = runs.data?.find((run) => run.id === runId) ?? null;

  const tracks = useQuery({
    queryKey: ["tracks", runId],
    queryFn: () => api(`/investigate/runs/${runId}/tracks`),
    enabled: Boolean(runId),
    refetchInterval: selectedRun && ACTIVE.has(selectedRun.status) ? 3_000 : false,
  });

  const wantedTrack = Number(searchParams.get("track"));
  useEffect(() => {
    if (!activeTrack && wantedTrack && tracks.data) {
      const match = tracks.data.find((track) => track.track_ref === wantedTrack);
      if (match) setActiveTrack(match);
    }
  }, [tracks.data, wantedTrack, activeTrack]);

  const canOperate = recording.data && canAccessDepartment(user, recording.data.department, "operator");
  const sortedTracks = useMemo(() => [...(tracks.data ?? [])].sort((a, b) => a.first_ms - b.first_ms), [tracks.data]);

  async function startRun(event) {
    event.preventDefault();
    setStarting(true);
    try {
      const run = await api(`/investigate/recordings/${id}/runs`, { method: "POST", json: { kind, imgsz: imgsz ? Number(imgsz) : null } });
      toast(`Ingest run #${run.id} queued`, { tone: "live" });
      setRunId(run.id);
      queryClient.invalidateQueries({ queryKey: ["runs", id] });
    } catch (error) {
      toast("Couldn't start ingest", { tone: "critical", detail: error.message });
    } finally {
      setStarting(false);
    }
  }

  async function cancel(run) {
    try {
      await api(`/investigate/runs/${run.id}/cancel`, { method: "POST" });
      queryClient.invalidateQueries({ queryKey: ["runs", id] });
    } catch (error) {
      toast("Couldn't cancel the run", { tone: "critical", detail: error.message });
    }
  }

  if (recording.isPending) return <Skeleton height={320} />;
  if (recording.isError) return <Notice tone="critical">{recording.error.message}</Notice>;
  const rec = recording.data;

  return (
    <>
      <div className={styles.detailHeader}>
        <Link to="/investigate" className="ui-btn ui-btn--ghost ui-btn--sm">
          <ArrowLeft aria-hidden="true" /> Recordings
        </Link>
        <h2>{rec.original_filename}</h2>
        <span className="faint">
          {rec.department}
          {rec.duration_seconds ? ` · ${fmtDuration(rec.duration_seconds)}` : ""}
          {rec.recorded_at ? ` · recorded ${fmtDateTime(rec.recorded_at)}` : " · unanchored"}
        </span>
      </div>

      {rec.status !== "ready" && (
        <Notice tone={rec.status === "rejected" ? "critical" : "pending"}>
          This recording is {rec.status}
          {rec.reject_reason ? `: ${rec.reject_reason}` : "."} Ingest can run once it's ready.
        </Notice>
      )}

      <Section title="Ingest runs">
        {canOperate && rec.status === "ready" && (
          <Toolbar label="Start ingest">
            <form onSubmit={startRun} className={styles.runForm}>
              <Select value={kind} onChange={(e) => setKind(e.target.value)} disabled={starting} aria-label="Ingest kind">
                <option value="vehicle">Vehicles and plates</option>
                <option value="person">People</option>
              </Select>
              <Select value={imgsz} onChange={(e) => setImgsz(e.target.value)} disabled={starting} aria-label="Inference size">
                <option value="">960 px (default)</option>
                <option value="640">640 px — faster, fewer distant subjects</option>
              </Select>
              <Button type="submit" variant="primary" icon={<ScanSearch />} loading={starting}>
                Run ingest
              </Button>
            </form>
          </Toolbar>
        )}

        {runs.isPending ? (
          <Skeleton height={120} />
        ) : (runs.data ?? []).length === 0 ? (
          <p className="faint">No ingest runs yet.</p>
        ) : (
          <div className="ui-table-wrap">
            <table className="ui-table">
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Kind</th>
                  <th>Status</th>
                  <th>Progress</th>
                  <th className="ui-table__num">Tracks</th>
                  <th>Started</th>
                  <th>
                    <span className="visually-hidden">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {runs.data.map((run) => {
                  const [label, tone] = RUN_STATUS[run.status] ?? [run.status];
                  return (
                    <tr key={run.id} className={styles.clickRow} data-selected={run.id === runId || undefined} onClick={() => setRunId(run.id)}>
                      <td className="data">#{run.id}</td>
                      <td>{run.kind}</td>
                      <td>
                        <Tooltip content={run.error ?? null}>
                          <span>
                            <Badge tone={tone}>{label}</Badge>
                          </span>
                        </Tooltip>
                        {run.status === "queued" && run.queue_position != null && <span className="faint"> · #{run.queue_position}</span>}
                      </td>
                      <td style={{ minWidth: 140 }}>
                        <div className={styles.progress}>
                          <div className="ui-meter">
                            <span className="ui-meter__fill" style={{ width: `${Math.round(run.progress_pct ?? 0)}%` }} />
                          </div>
                          <span className="data faint">{Math.round(run.progress_pct ?? 0)}%</span>
                        </div>
                      </td>
                      <td className="ui-table__num data">{run.track_count}</td>
                      <td className="data">{run.started_at ? fmtDateTime(run.started_at) : "—"}</td>
                      <td>
                        {ACTIVE.has(run.status) && canOperate && (
                          <div className="ui-table__actions">
                            <IconButton
                              label="Cancel run"
                              size="sm"
                              onClick={(event) => {
                                event.stopPropagation();
                                cancel(run);
                              }}
                            >
                              <X />
                            </IconButton>
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      {activeTrack && (
        <div ref={playerRef} className={styles.playerAnchor}>
          <Section title={`Occurrence ${activeTrack.occurrence_index}`} description={occurrenceTime(rec, activeTrack)} actions={<Button variant="ghost" size="sm" onClick={() => setActiveTrack(null)}>Close player</Button>}>
            <TrackOverlayPlayer recordingId={rec.id} runId={activeTrack.run_id} trackRef={activeTrack.track_ref} firstMs={activeTrack.first_ms} />
          </Section>
        </div>
      )}

      {selectedRun && (
        <Section title={`Tracks · run #${selectedRun.id}`}>
          {tracks.isPending ? (
            <Skeleton height={160} />
          ) : sortedTracks.length === 0 ? (
            <EmptyState compact title="No tracks yet">
              {ACTIVE.has(selectedRun.status) ? "Tracks appear as the run processes the recording." : "This run didn't extract any tracks."}
            </EmptyState>
          ) : (
            <TrackGrid tracks={sortedTracks} recording={rec} activeRef={activeTrack?.track_ref ?? null} onPlay={setActiveTrack} onZoom={setLightbox} />
          )}
        </Section>
      )}

      <Dialog open={Boolean(lightbox)} onClose={() => setLightbox(null)} title={lightbox ? `Occurrence ${lightbox.occurrence_index}` : ""} wide>
        {lightbox && <img src={trackThumbUrl(lightbox.run_id, lightbox.track_ref)} alt="Track crop" className={styles.lightbox} />}
      </Dialog>
    </>
  );
}
