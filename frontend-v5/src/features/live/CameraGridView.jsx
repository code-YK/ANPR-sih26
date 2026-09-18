import { Cctv, LayoutGrid, Rows2, Search, Square } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { EmptyState, Input, Segmented, Select, Skeleton, Tooltip } from "../../components/ui.jsx";
import { usePageTitle } from "../../lib/hooks.js";
import { useDepartments } from "../../lib/queries.js";
import { useUiStore } from "../../lib/uiStore.js";
import { useStatusRows } from "../workers/useWorkers.js";
import CameraTile from "./CameraTile.jsx";
import ModeBadge from "./ModeBadge.jsx";
import { hasPreview, useLiveCameras } from "./useLiveCameras.js";
import styles from "./CameraGrid.module.css";

const PREVIEW_LIMITS = [3, 6, 9, 12, 16];

export default function CameraGridView() {
  usePageTitle("Live");
  const { cameras, isLoading, governmentMode, demoMode } = useLiveCameras();
  const departments = useDepartments();
  const { rows } = useStatusRows();
  const gridColumns = useUiStore((state) => state.gridColumns);
  const setGridColumns = useUiStore((state) => state.setGridColumns);
  const previewLimit = useUiStore((state) => state.previewLimit);
  const setPreviewLimit = useUiStore((state) => state.setPreviewLimit);

  const [query, setQuery] = useState("");
  const [scope, setScope] = useState("all");
  const [department, setDepartment] = useState("");

  const workersByCamera = useMemo(() => {
    const map = new Map();
    for (const row of rows) {
      if (!map.has(row.camera_id)) map.set(row.camera_id, []);
      map.get(row.camera_id).push(row);
    }
    return map;
  }, [rows]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return cameras.filter((camera) => {
      if (department && camera.department !== department) return false;
      if (scope === "ai" && !workersByCamera.has(camera.camera_id)) return false;
      if (scope === "anpr" && camera.anpr_viable !== true) return false;
      if (needle) {
        const haystack = [camera.camera_id, camera.name, camera.location_text, camera.department].join(" ").toLowerCase();
        if (!haystack.includes(needle)) return false;
      }
      return true;
    });
  }, [cameras, query, scope, department, workersByCamera]);

  // ---- Preview budget: which tiles hold a live connection ------------------
  // Sticky: a tile that is already playing keeps its slot while visible, so
  // scrolling a row away and back doesn't tear a healthy player down.
  const [visibleIds, setVisibleIds] = useState(() => new Set());
  const observerRef = useRef(null);
  const elements = useRef(new Map());

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        setVisibleIds((previous) => {
          let next = previous;
          for (const entry of entries) {
            const id = entry.target.dataset.cameraId;
            if (entry.isIntersecting === previous.has(id)) continue;
            if (next === previous) next = new Set(previous);
            if (entry.isIntersecting) next.add(id);
            else next.delete(id);
          }
          return next;
        });
      },
      { rootMargin: "120px 0px", threshold: 0.01 },
    );
    observerRef.current = observer;
    for (const element of elements.current.values()) observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const registerTile = useCallback((cameraId, element) => {
    const previous = elements.current.get(cameraId);
    if (previous && previous !== element) observerRef.current?.unobserve(previous);
    if (element) {
      elements.current.set(cameraId, element);
      observerRef.current?.observe(element);
    } else {
      elements.current.delete(cameraId);
    }
  }, []);

  const [activeIds, setActiveIds] = useState(() => new Set());
  const filteredKey = filtered.map((camera) => camera.camera_id).join("|");

  useEffect(() => {
    setActiveIds((previous) => {
      const next = new Set();
      let budget = previewLimit;
      const eligible = (camera) => hasPreview(camera) && visibleIds.has(camera.camera_id);
      const byId = new Map(filtered.map((camera) => [camera.camera_id, camera]));
      for (const id of previous) {
        if (budget <= 0) break;
        const camera = byId.get(id);
        if (camera && eligible(camera)) {
          next.add(id);
          budget -= 1;
        }
      }
      for (const camera of filtered) {
        if (budget <= 0) break;
        if (!next.has(camera.camera_id) && eligible(camera)) {
          next.add(camera.camera_id);
          budget -= 1;
        }
      }
      const same = next.size === previous.size && [...next].every((id) => previous.has(id));
      return same ? previous : next;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visibleIds, previewLimit, filteredKey]);

  const streamable = filtered.filter(hasPreview).length;
  const aiCameraCount = cameras.filter((camera) => workersByCamera.has(camera.camera_id)).length;

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.titleBlock}>
          <p className="overline">Live</p>
          <h1>Cameras</h1>
          <p className={styles.summary}>
            <span className="tabular">{cameras.length}</span> cameras
            <span className={styles.sep} aria-hidden="true">·</span>
            <span className="tabular">{Math.min(activeIds.size, streamable)}</span> of {streamable} previewing
            <span className={styles.sep} aria-hidden="true">·</span>
            <span className="tabular">{aiCameraCount}</span> with AI running
          </p>
        </div>
        <ModeBadge governmentMode={governmentMode} demoMode={demoMode} />
      </header>

      <div className={styles.toolbar} role="toolbar" aria-label="Camera filters">
        <div className={`ui-search ${styles.search}`}>
          <Search aria-hidden="true" />
          <Input
            type="search"
            placeholder="Search name, location or ID"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-label="Search cameras"
          />
        </div>
        <Segmented
          label="Camera scope"

          value={scope}
          onChange={setScope}
          options={[
            { value: "all", label: "All" },
            { value: "ai", label: "AI running" },
            { value: "anpr", label: "Plate-readable" },
          ]}
        />
        <Select value={department} onChange={(event) => setDepartment(event.target.value)} aria-label="Department" className={styles.select}>
          <option value="">All departments</option>
          {(departments.data ?? []).map((item) => (
            <option key={item.name} value={item.name}>
              {item.name}
            </option>
          ))}
        </Select>
        <div className={styles.spacer} />
        <Tooltip content="How many tiles may hold a live stream at once. Each is a separate stream copy.">
          <label className={styles.limit}>
            <span className="faint">Live previews</span>
            <Select size="sm" value={previewLimit} onChange={(event) => setPreviewLimit(Number(event.target.value))} aria-label="Live preview limit">
              {PREVIEW_LIMITS.map((limit) => (
                <option key={limit} value={limit}>
                  {limit}
                </option>
              ))}
            </Select>
          </label>
        </Tooltip>
        <Segmented
          size="sm"
          label="Grid density"

          value={gridColumns}
          onChange={setGridColumns}
          options={[
            { value: 2, label: <span className="visually-hidden">2 columns</span>, icon: <Rows2 size={15} aria-hidden="true" />, title: "Large" },
            { value: 3, label: <span className="visually-hidden">3 columns</span>, icon: <LayoutGrid size={15} aria-hidden="true" />, title: "Medium" },
            { value: 4, label: <span className="visually-hidden">4 columns</span>, icon: <Square size={13} aria-hidden="true" />, title: "Compact" },
          ]}
        />
      </div>

      {isLoading ? (
        <div className={styles.grid} style={{ "--cols": gridColumns }}>
          {Array.from({ length: 6 }, (_, index) => (
            <Skeleton key={index} className={styles.tileSkeleton} />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <EmptyState icon={<Cctv />} title={cameras.length === 0 ? "No cameras you can view" : "No cameras match"}>
          {cameras.length === 0
            ? "Cameras appear here once they are onboarded in Registry and your account has access to their department."
            : "Try a different search or clear the filters."}
        </EmptyState>
      ) : (
        <div className={styles.grid} style={{ "--cols": gridColumns }}>
          {filtered.map((camera, index) => (
            <CameraTile
              key={camera.camera_id}
              camera={camera}
              index={index}
              active={activeIds.has(camera.camera_id)}
              visible={visibleIds.has(camera.camera_id)}
              workers={workersByCamera.get(camera.camera_id)}
              register={registerTile}
            />
          ))}
        </div>
      )}
    </div>
  );
}
