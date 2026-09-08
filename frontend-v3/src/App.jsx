import { Navigate, NavLink, Route, Routes } from "react-router-dom";

import AlertsNavBadge from "./context/AlertsNavBadge.jsx";
import { AlertsProvider } from "./context/AlertsContext.jsx";
import { AuthProvider, isDepartmentAdmin, isSuperAdmin, useAuth } from "./context/AuthContext.jsx";
import { CamerasProvider } from "./context/CamerasContext.jsx";
import { DepartmentsProvider } from "./context/DepartmentsContext.jsx";
import LoadingScreen from "./components/LoadingScreen.jsx";
import LogsPanel from "./components/LogsPanel.jsx";
import SentinelMark from "./components/SentinelMark.jsx";
import StatusStrip from "./components/StatusStrip.jsx";
import { ToastProvider, useToast } from "./components/Toast.jsx";
import { useFormValidationTheme } from "./hooks/useFormValidationTheme.js";
import AdminView from "./views/Admin/AdminView.jsx";
import AlertsView from "./views/Alerts/AlertsView.jsx";
import AuthView from "./views/Auth/AuthView.jsx";
import InvestigateView from "./views/Investigate/InvestigateView.jsx";
import JourneyView from "./views/Journey/JourneyView.jsx";
import LiveView from "./views/Live/LiveView.jsx";
import RegistryView from "./views/Registry/RegistryView.jsx";
import WatchlistView from "./views/Watchlist/WatchlistView.jsx";

function navClass({ isActive }) {
  return isActive ? "nav-btn active" : "nav-btn";
}

function AuthenticatedApp() {
  const { user, loading, logout } = useAuth();
  // Registered here rather than per-form: it listens in the capture phase at
  // the document, so it covers the sign-in form and every modal at once.
  useFormValidationTheme(useToast());

  if (loading) return <LoadingScreen />;
  if (!user) return <AuthView />;

  const canAdminister = isSuperAdmin(user) || isDepartmentAdmin(user);

  return (
    <DepartmentsProvider>
      <CamerasProvider>
        <AlertsProvider>
          <div className="app-shell">
            <header className="app-rail">
              <h1 className="wordmark">
                <SentinelMark size={26} />
                <span>
                  Sentinel
                  <span className="sub">Operator Console</span>
                </span>
              </h1>
              <nav>
                <NavLink to="/live" className={navClass}>Live</NavLink>
                <NavLink to="/alerts" className={navClass}>
                  Alerts <AlertsNavBadge />
                </NavLink>
                <NavLink to="/journey" className={navClass}>Journey</NavLink>
                <NavLink to="/investigate" className={navClass}>Investigate</NavLink>
                <NavLink to="/watchlist" className={navClass}>Watchlist</NavLink>
                <NavLink to="/registry" className={navClass}>Registry</NavLink>
                {canAdminister && <NavLink to="/admin" className={navClass}>Access admin</NavLink>}
              </nav>
              <div className="session-summary">
                <span>
                  <strong>{user.full_name}</strong>
                  <small>{user.role.replaceAll("_", " ")}{user.home_department ? ` · ${user.home_department}` : ""}</small>
                </span>
                <button className="secondary" onClick={logout}>Sign out</button>
              </div>
            </header>

            <main>
              <Routes>
                <Route path="/" element={<Navigate to="/live" replace />} />
                <Route path="/live" element={<LiveView />} />
                <Route path="/alerts/*" element={<AlertsView />} />
                <Route path="/journey" element={<JourneyView />} />
                <Route path="/journey/:plate" element={<JourneyView />} />
                <Route path="/investigate/*" element={<InvestigateView />} />
                <Route path="/watchlist" element={<WatchlistView />} />
                <Route path="/registry/*" element={<RegistryView />} />
                <Route path="/admin" element={canAdminister ? <AdminView /> : <Navigate to="/live" replace />} />
                <Route path="*" element={<Navigate to="/live" replace />} />
              </Routes>
            </main>

            <StatusStrip />
            <LogsPanel />
          </div>
        </AlertsProvider>
      </CamerasProvider>
    </DepartmentsProvider>
  );
}

export default function App() {
  return (
    <ToastProvider>
      <AuthProvider>
        <AuthenticatedApp />
      </AuthProvider>
    </ToastProvider>
  );
}
