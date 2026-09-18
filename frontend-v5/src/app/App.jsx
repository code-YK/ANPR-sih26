import { useCallback } from "react";

import { Spinner } from "../components/ui.jsx";
import SentinelMark from "../components/SentinelMark.jsx";
import { AuthProvider, useAuth } from "../features/auth/AuthProvider.jsx";
import SignInView from "../features/auth/SignInView.jsx";
import { useNotificationStore } from "../features/notifications/notificationStore.js";
import { useWorkerStore } from "../features/workers/workerStore.js";
import { useUiStore } from "../lib/uiStore.js";
import Shell from "./Shell.jsx";
import styles from "./Shell.module.css";

function Gate() {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className={styles.boot} role="status" aria-label="Loading Sentinel">
        <SentinelMark size={40} />
        <Spinner />
      </div>
    );
  }
  return user ? <Shell /> : <SignInView />;
}

export default function App() {
  // Signing out ends this browser session's Workspace view. Workers keep
  // running on the server; the next operator starts from a clean slate.
  const onSignedOut = useCallback(() => {
    useWorkerStore.getState().clear();
    useNotificationStore.getState().clear();
    useUiStore.setState({ workspaceOpen: false, logsOpen: false, sheetCameraId: null, activeTab: {} });
  }, []);

  return (
    <AuthProvider onSignedOut={onSignedOut}>
      <Gate />
    </AuthProvider>
  );
}
