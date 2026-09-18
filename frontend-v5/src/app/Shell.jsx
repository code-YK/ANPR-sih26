import { lazy, Suspense, useEffect } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import { ErrorBoundary, PageError } from "../components/ErrorBoundary.jsx";
import { Skeleton } from "../components/ui.jsx";
import CameraGridView from "../features/live/CameraGridView.jsx";
import FocusedCameraView from "../features/live/FocusedCameraView.jsx";
import LogsDock from "../features/logs/LogsDock.jsx";
import EventFeedSync from "../features/notifications/EventFeedSync.jsx";
import NotificationStack from "../features/notifications/NotificationStack.jsx";
import WorkerStatusSync from "../features/workers/WorkerStatusSync.jsx";
import { WorkspacePanel, WorkspaceRail } from "../features/workspace/Workspace.jsx";
import { onAudioBlockedChange } from "../lib/audio/soundEngine.js";
import { canAdminister } from "../lib/permissions.js";
import { useUiStore } from "../lib/uiStore.js";
import { useAuth } from "../features/auth/AuthProvider.jsx";
import TopBar from "./TopBar.jsx";
import styles from "./Shell.module.css";

const AlertsView = lazy(() => import("../features/alerts/AlertsView.jsx"));
const JourneyView = lazy(() => import("../features/journey/JourneyView.jsx"));
const WatchlistView = lazy(() => import("../features/watchlist/WatchlistView.jsx"));
const RegistryView = lazy(() => import("../features/registry/RegistryView.jsx"));
const InvestigateView = lazy(() => import("../features/investigate/InvestigateView.jsx"));
const AdminView = lazy(() => import("../features/admin/AdminView.jsx"));

function PageFallback() {
  return (
    <div className={styles.fallback} aria-busy="true">
      <Skeleton width={220} height={30} />
      <Skeleton width="60%" height={16} />
      <Skeleton height={320} style={{ marginTop: 12 }} />
    </div>
  );
}

function ScrollReset() {
  const { pathname } = useLocation();
  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [pathname]);
  return null;
}

export default function Shell() {
  const { user } = useAuth();
  const { pathname } = useLocation();
  const setSoundBlocked = useUiStore((state) => state.setSoundBlocked);

  useEffect(() => onAudioBlockedChange(setSoundBlocked), [setSoundBlocked]);

  return (
    <div className={styles.shell}>
      <a href="#main" className={styles.skip}>
        Skip to content
      </a>
      <TopBar />
      <main id="main" className={styles.main}>
        <ScrollReset />
        <ErrorBoundary name="page" resetKey={pathname} fallback={<PageError />}>
          <Suspense fallback={<PageFallback />}>
            <Routes>
              <Route path="/" element={<Navigate to="/live" replace />} />
              <Route path="/live" element={<CameraGridView />} />
              <Route path="/live/:cameraId" element={<FocusedCameraView />} />
              <Route path="/alerts/*" element={<AlertsView />} />
              <Route path="/journeys" element={<JourneyView />} />
              <Route path="/journeys/:plate" element={<JourneyView />} />
              <Route path="/investigate/*" element={<InvestigateView />} />
              <Route path="/watchlist" element={<WatchlistView />} />
              <Route path="/registry/*" element={<RegistryView />} />
              <Route path="/admin/*" element={canAdminister(user) ? <AdminView /> : <Navigate to="/live" replace />} />
              {/* v3 paths, kept so old links keep working */}
              <Route path="/journey" element={<Navigate to="/journeys" replace />} />
              <Route path="/journey/:plate" element={<LegacyJourneyRedirect />} />
              <Route path="*" element={<Navigate to="/live" replace />} />
            </Routes>
          </Suspense>
        </ErrorBoundary>
      </main>

      <ErrorBoundary name="workspace">
        <WorkspaceRail />
        <WorkspacePanel />
      </ErrorBoundary>
      <ErrorBoundary name="notifications">
        <NotificationStack />
      </ErrorBoundary>
      <ErrorBoundary name="logs">
        <LogsDock />
      </ErrorBoundary>

      <ErrorBoundary name="worker-sync">
        <WorkerStatusSync />
      </ErrorBoundary>
      <ErrorBoundary name="event-feed">
        <EventFeedSync />
      </ErrorBoundary>
    </div>
  );
}

function LegacyJourneyRedirect() {
  const { pathname } = useLocation();
  return <Navigate to={pathname.replace(/^\/journey\//, "/journeys/")} replace />;
}
