import { useEffect, useMemo, useRef, useState } from "react";
import { Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
import {
  Activity,
  Bell,
  Camera,
  LogOut,
  MapPinned,
  Moon,
  PanelLeft,
  PanelTop,
  Route as RouteIcon,
  Search,
  Shield,
  Sun,
  Palette,
  Volume2,
  VolumeX,
} from "lucide-react";

import AlertsNavBadge from "./context/AlertsNavBadge.jsx";
import { AlertsProvider } from "./context/AlertsContext.jsx";
import { AuthProvider, isDepartmentAdmin, isSuperAdmin, useAuth } from "./context/AuthContext.jsx";
import { CamerasProvider, useCameras } from "./context/CamerasContext.jsx";
import { DepartmentsProvider } from "./context/DepartmentsContext.jsx";
import { ThemeProvider, useTheme } from "./context/ThemeContext.jsx";
import ErrorBoundary from "./components/ErrorBoundary.jsx";
import LoadingScreen from "./components/LoadingScreen.jsx";
import Copilot from "./components/Copilot.jsx";
import LogsPanel from "./components/LogsPanel.jsx";
import BrandMark from "./components/BrandMark.jsx";
import StatusStrip from "./components/StatusStrip.jsx";
import { ToastProvider, useToast } from "./components/Toast.jsx";
import { useFormValidationTheme } from "./hooks/useFormValidationTheme.js";
import { useAnalyticsStatus } from "./lib/analyticsStatus.js";
import { setSoundEnabled, useSoundEnabled } from "./lib/notifications.js";
import AdminView from "./views/Admin/AdminView.jsx";
import AlertsView from "./views/Alerts/AlertsView.jsx";
import AuthView from "./views/Auth/AuthView.jsx";
import InvestigateView from "./views/Investigate/InvestigateView.jsx";
import JourneyView from "./views/Journey/JourneyView.jsx";
import LandingView from "./views/Landing/LandingView.jsx";
import LiveView from "./views/Live/LiveView.jsx";
import RegistryView from "./views/Registry/RegistryView.jsx";
import WatchlistView from "./views/Watchlist/WatchlistView.jsx";

function navClass({ isActive }) {
  return isActive ? "nav-btn active" : "nav-btn";
}

// Mute for the alert and sighting sounds (lib/notifications.js). Cards still
// appear either way; this only silences them.
function SoundToggle() {
  const enabled = useSoundEnabled();
  return (
    <button
      type="button"
      className="secondary theme-toggle"
      onClick={() => setSoundEnabled(!enabled)}
      aria-pressed={enabled}
      title={enabled ? "Mute alert sounds" : "Turn alert sounds on"}
      aria-label={enabled ? "Mute alert sounds" : "Turn alert sounds on"}
    >
      {enabled ? <Volume2 size={16} strokeWidth={2} /> : <VolumeX size={16} strokeWidth={2} />}
      <span className="theme-toggle-label">{enabled ? "Sound" : "Muted"}</span>
    </button>
  );
}

function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();
  const isLight = theme === "light";
  return (
    <button
      type="button"
      className="secondary theme-toggle"
      onClick={toggleTheme}
      title={isLight ? "Switch to dark mode" : "Switch to light mode"}
      aria-label={isLight ? "Switch to dark mode" : "Switch to light mode"}
    >
      {isLight ? <Moon size={16} strokeWidth={2} /> : <Sun size={16} strokeWidth={2} />}
      <span className="theme-toggle-label">{isLight ? "Dark" : "Light"}</span>
    </button>
  );
}

function ColorSwitch() {
  const { accent, setAccent, accents } = useTheme();
  const [open, setOpen] = useState(false);
  const [menuStyle, setMenuStyle] = useState(null);
  const rootRef = useRef(null);
  const btnRef = useRef(null);
  const current = accents.find((c) => c.id === accent) ?? accents[0];

  useEffect(() => {
    if (!open) {
      setMenuStyle(null);
      return undefined;
    }

    function place() {
      const btn = btnRef.current;
      if (!btn) return;
      const r = btn.getBoundingClientRect();
      const menuW = 228;
      const gap = 10;
      const spaceRight = window.innerWidth - r.right;
      // Prefer open to the right of the rail button; fall back below if tight
      let left = r.right + gap;
      let top = Math.max(12, r.bottom - 280);
      if (spaceRight < menuW + 16) {
        left = Math.max(12, r.left);
        top = r.bottom + gap;
      }
      const maxH = Math.min(420, window.innerHeight - top - 16);
      setMenuStyle({
        position: "fixed",
        left: `${left}px`,
        top: `${top}px`,
        zIndex: 10000,
        maxHeight: `${maxH}px`,
      });
    }

    place();
    function onDoc(e) {
      if (rootRef.current && !rootRef.current.contains(e.target)) setOpen(false);
    }
    function onKey(e) {
      if (e.key === "Escape") setOpen(false);
    }
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    document.addEventListener("pointerdown", onDoc, true);
    document.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
      document.removeEventListener("pointerdown", onDoc, true);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  function pick(e, id) {
    e.preventDefault();
    e.stopPropagation();
    setAccent(id);
    setOpen(false);
  }

  return (
    <div className="color-switch" ref={rootRef}>
      <button
        ref={btnRef}
        type="button"
        className="secondary theme-toggle color-switch-btn"
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        title={`Theme color: ${current.label}`}
        aria-label={`Theme color: ${current.label}. Open color switch`}
        aria-expanded={open}
      >
        <span
          className="color-switch-swatch"
          style={{ background: `hsl(${current.hue} ${current.sat}% 50%)` }}
          aria-hidden="true"
        />
        <Palette size={15} strokeWidth={2} />
        <span className="theme-toggle-label">Color</span>
      </button>
      {open && (
        <div
          className="color-switch-menu color-switch-menu-fixed"
          role="listbox"
          aria-label="Theme colors"
          style={menuStyle || { position: "fixed", zIndex: 10000 }}
          onPointerDown={(e) => e.stopPropagation()}
        >
          {accents.map((c) => (
            <button
              key={c.id}
              type="button"
              role="option"
              aria-selected={c.id === accent}
              className={c.id === accent ? "color-switch-option is-active" : "color-switch-option"}
              onPointerDown={(e) => pick(e, c.id)}
              onClick={(e) => pick(e, c.id)}
              title={c.label}
            >
              <span
                className="color-switch-swatch"
                style={{ background: `hsl(${c.hue} ${c.sat}% 50%)` }}
                aria-hidden="true"
              />
              <span>{c.label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function userInitials(user) {
  const name = (user?.full_name || user?.email || "OP").trim();
  const parts = name.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return name.slice(0, 2).toUpperCase();
}

/** Live / AI summary chip shown in the horizontal top bar (matches control-room mock). */
function TopbarLiveStatus() {
  const { cameras } = useCameras();
  const { rows: workers } = useAnalyticsStatus();
  const aiRunning = workers.filter((row) => row.state === "running" || row.running).length;

  const live = useMemo(
    () => cameras.filter((c) => c.is_live === true).length,
    [cameras],
  );

  return (
    <div className="topbar-status" title={`${live} of ${cameras.length} cameras live · ${aiRunning} AI workers`}>
      <span className="topbar-status-dot" aria-hidden="true" />
      <span className="topbar-status-text">
        {live} / {cameras.length} live
        <span className="topbar-status-sep">|</span>
        {aiRunning} AI
      </span>
    </div>
  );
}

function AuthenticatedShell() {
  const location = useLocation();
  const { user, logout } = useAuth();
  const canAdminister = isSuperAdmin(user) || isDepartmentAdmin(user);
  const [navLayout, setNavLayout] = useState(() => {
    try {
      return localStorage.getItem("citytrace-nav-layout") === "horizontal" ? "horizontal" : "vertical";
    } catch {
      return "vertical";
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem("citytrace-nav-layout", navLayout);
    } catch {
      /* ignore */
    }
    document.documentElement.dataset.navLayout = navLayout;
  }, [navLayout]);

  const isHorizontal = navLayout === "horizontal";

  function toggleNavLayout() {
    setNavLayout((prev) => (prev === "vertical" ? "horizontal" : "vertical"));
  }

  const opsNav = (
    <>
      <NavLink to="/live" className={navClass}>
        <Activity size={17} strokeWidth={1.75} className="rail-nav-icon" />
        <span>Live</span>
      </NavLink>
      <NavLink to="/alerts" className={navClass}>
        <Bell size={17} strokeWidth={1.75} className="rail-nav-icon" />
        <span>Alerts</span>
        <AlertsNavBadge />
      </NavLink>
      <NavLink to="/journey" className={navClass}>
        <RouteIcon size={17} strokeWidth={1.75} className="rail-nav-icon" />
        <span>{isHorizontal ? "Journeys" : "Journey"}</span>
      </NavLink>
      <NavLink to="/investigate" className={navClass}>
        <Search size={17} strokeWidth={1.75} className="rail-nav-icon" />
        <span>Investigate</span>
      </NavLink>
    </>
  );

  const intelNav = (
    <>
      <NavLink to="/watchlist" className={navClass}>
        <Shield size={17} strokeWidth={1.75} className="rail-nav-icon" />
        <span>Watchlist</span>
      </NavLink>
      <NavLink to="/registry" className={navClass}>
        <MapPinned size={17} strokeWidth={1.75} className="rail-nav-icon" />
        <span>Registry</span>
      </NavLink>
      {canAdminister && (
        <NavLink to="/admin" className={navClass}>
          <Camera size={17} strokeWidth={1.75} className="rail-nav-icon" />
          <span>{isHorizontal ? "Admin" : "Access admin"}</span>
        </NavLink>
      )}
    </>
  );

  return (
    <DepartmentsProvider>
      <CamerasProvider>
        <AlertsProvider>
          <div className={`app-shell layout-${navLayout}`}>
            <header className={isHorizontal ? "app-topbar" : "app-rail"}>
              {!isHorizontal && <div className="rail-glow" aria-hidden="true" />}
              <h1 className="wordmark rail-brand">
                <BrandMark size={isHorizontal ? 24 : 30} />
                <span>
                  CityTraceAI
                  {!isHorizontal && <span className="sub">Operator Console</span>}
                </span>
              </h1>

              {isHorizontal ? (
                <nav className="topbar-nav" aria-label="Primary">
                  {opsNav}
                  {intelNav}
                </nav>
              ) : (
                <>
                  <div className="rail-section">
                    <p className="rail-section-label">Operations</p>
                    <nav className="rail-nav" aria-label="Primary">
                      {opsNav}
                    </nav>
                  </div>
                  <div className="rail-section">
                    <p className="rail-section-label">Intelligence</p>
                    <nav className="rail-nav" aria-label="Intelligence">
                      {intelNav}
                    </nav>
                  </div>
                </>
              )}

              <div className={isHorizontal ? "topbar-end" : "session-summary"}>
                {!isHorizontal && (
                  <>
                    <div className="session-identity">
                      <span className="session-avatar" aria-hidden="true">
                        {userInitials(user)}
                      </span>
                      <span className="session-identity-text">
                        <strong>{user?.full_name || user?.email || "Operator"}</strong>
                        <small>{user?.role?.replaceAll("_", " ") || "signed in"}</small>
                      </span>
                    </div>
                    <div className="session-actions">
                      <button
                        type="button"
                        className="secondary theme-toggle layout-toggle"
                        onClick={toggleNavLayout}
                        title="Switch to horizontal top bar"
                        aria-label="Switch to horizontal top bar"
                      >
                        <PanelTop size={16} strokeWidth={2} />
                        <span className="theme-toggle-label">Top bar</span>
                      </button>
                      <SoundToggle />
                      <SoundToggle />
                    <ThemeToggle />
                      <ColorSwitch />
                      <button type="button" className="secondary rail-signout" onClick={logout} title="Sign out">
                        <LogOut size={16} strokeWidth={2} />
                        <span className="theme-toggle-label">Sign out</span>
                      </button>
                    </div>
                  </>
                )}
                {isHorizontal && (
                  <>
                    <TopbarLiveStatus />
                    <button
                      type="button"
                      className="secondary theme-toggle layout-toggle"
                      onClick={toggleNavLayout}
                      title="Switch to vertical sidebar"
                      aria-label="Switch to vertical sidebar"
                    >
                      <PanelLeft size={16} strokeWidth={2} />
                      <span className="theme-toggle-label">Sidebar</span>
                    </button>
                    <ThemeToggle />
                    <ColorSwitch />
                    <button type="button" className="secondary rail-signout" onClick={logout} title="Sign out">
                      <LogOut size={16} strokeWidth={2} />
                      <span className="theme-toggle-label">Sign out</span>
                    </button>
                    <span className="topbar-avatar" title={user?.full_name || user?.email || "Operator"}>
                      {userInitials(user)}
                    </span>
                  </>
                )}
              </div>
            </header>

            <main>
              <ErrorBoundary resetKey={location.pathname}>
              <Routes>
                <Route path="/live" element={<LiveView />} />
                <Route path="/live/:cameraId" element={<LiveView />} />
                <Route path="/alerts/*" element={<AlertsView />} />
                <Route path="/journey" element={<JourneyView />} />
                <Route path="/journey/:plate" element={<JourneyView />} />
                <Route path="/investigate/*" element={<InvestigateView />} />
                <Route path="/watchlist" element={<WatchlistView />} />
                <Route path="/registry/*" element={<RegistryView />} />
                <Route path="/admin/*" element={canAdminister ? <AdminView /> : <Navigate to="/live" replace />} />
                <Route path="/login" element={<Navigate to="/live" replace />} />
                <Route path="*" element={<Navigate to="/live" replace />} />
              </Routes>
              </ErrorBoundary>
            </main>

            <StatusStrip />
            <LogsPanel />
            <Copilot />
          </div>
        </AlertsProvider>
      </CamerasProvider>
    </DepartmentsProvider>
  );
}

function PublicRoutes() {
  return (
    <Routes>
      <Route path="/" element={<LandingView />} />
      <Route path="/login" element={<AuthView />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

function RootApp() {
  const { user, loading } = useAuth();
  useFormValidationTheme(useToast());

  if (loading) return <LoadingScreen />;
  if (!user) return <PublicRoutes />;
  return <AuthenticatedShell />;
}

export default function App() {
  return (
    <ThemeProvider>
      <ToastProvider>
        <AuthProvider>
          <RootApp />
        </AuthProvider>
      </ToastProvider>
    </ThemeProvider>
  );
}
