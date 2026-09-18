import { Layers, LogOut, Menu, Volume2, VolumeX } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";

import { IconButton, Spinner, Tooltip } from "../components/ui.jsx";
import SentinelMark from "../components/SentinelMark.jsx";
import { useAuth } from "../features/auth/AuthProvider.jsx";
import { playSound } from "../lib/audio/soundEngine.js";
import { humanize } from "../lib/format.js";
import { canAdminister, isSuperAdmin } from "../lib/permissions.js";
import { useAnalyticsStatus, useCameras, useOpenAlerts } from "../lib/queries.js";
import { useUiStore } from "../lib/uiStore.js";
import styles from "./Shell.module.css";

function useNavItems(user) {
  const items = [
    { to: "/live", label: "Live" },
    { to: "/alerts", label: "Alerts", badge: true },
    { to: "/journeys", label: "Journeys" },
    { to: "/investigate", label: "Investigate" },
    { to: "/watchlist", label: "Watchlist" },
    { to: "/registry", label: "Registry" },
  ];
  if (canAdminister(user)) items.push({ to: "/admin", label: "Admin" });
  return items;
}

function NavItems({ items, openAlerts, onNavigate, vertical = false }) {
  const { pathname } = useLocation();
  return items.map((item) => {
    const active = pathname === item.to || pathname.startsWith(`${item.to}/`);
    return (
      <NavLink key={item.to} to={item.to} className={styles.navLink} data-active={active || undefined} onClick={onNavigate} aria-current={active ? "page" : undefined}>
        {item.label}
        {item.badge && openAlerts > 0 && (
          <span className={styles.navBadge} aria-label={`${openAlerts} open`}>
            {openAlerts > 99 ? "99+" : openAlerts}
          </span>
        )}
        {!vertical && <span className={styles.navUnderline} aria-hidden="true" />}
      </NavLink>
    );
  });
}

function EstateStatus() {
  const cameras = useCameras();
  const status = useAnalyticsStatus();
  const live = (cameras.data ?? []).filter((camera) => camera.is_live === true).length;
  const total = cameras.data?.length ?? 0;
  const workers = (status.data ?? []).filter((row) => row.state === "running").length;
  const offline = status.isError && cameras.isError;
  return (
    <Tooltip content={offline ? "The console can't reach the backend right now." : "Catalogue-reported live cameras · AI workers running now"}>
      <div className={styles.estate} data-offline={offline || undefined}>
        <span className={styles.estateItem}>
          <span className={styles.estateDot} data-tone={offline ? "critical" : "live"} aria-hidden="true" />
          <span className="tabular">{live}</span>
          <span className="faint">/{total} live</span>
        </span>
        <span className={styles.estateSep} aria-hidden="true" />
        <span className={styles.estateItem}>
          <span className="tabular">{workers}</span>
          <span className="faint">AI</span>
        </span>
      </div>
    </Tooltip>
  );
}

function SoundToggle() {
  const enabled = useUiStore((state) => state.soundEnabled);
  const blocked = useUiStore((state) => state.soundBlocked);
  const setEnabled = useUiStore((state) => state.setSoundEnabled);
  const label = enabled ? (blocked ? "Sound on — waiting for a click to unlock" : "Mute notification sounds") : "Unmute notification sounds";
  return (
    <IconButton
      label={label}
      aria-pressed={!enabled}
      className={styles.soundButton}
      data-blocked={(enabled && blocked) || undefined}
      onClick={() => {
        const next = !enabled;
        setEnabled(next);
        if (next) playSound("sighting");
      }}
    >
      {enabled ? <Volume2 /> : <VolumeX />}
    </IconButton>
  );
}

function UserMenu({ user, logout }) {
  const [open, setOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const onDown = (event) => {
      if (ref.current && !ref.current.contains(event.target)) setOpen(false);
    };
    const onKey = (event) => event.key === "Escape" && setOpen(false);
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const initials = (user.full_name || user.email || "?")
    .split(/\s+/)
    .map((part) => part[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
  const scope = isSuperAdmin(user)
    ? "All departments"
    : `${user.grants?.length ?? 0} department${user.grants?.length === 1 ? "" : "s"}`;

  return (
    <div className={styles.userMenu} ref={ref}>
      <button type="button" className={styles.avatar} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}>
        {initials}
        <span className="visually-hidden">Account menu</span>
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            role="menu"
            className={styles.menu}
            initial={{ opacity: 0, y: -4, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, transition: { duration: 0.12 } }}
            transition={{ duration: 0.18, ease: [0.16, 1, 0.3, 1] }}
          >
            <div className={styles.menuIdentity}>
              <strong>{user.full_name}</strong>
              <span>{user.email}</span>
              <span className={styles.menuRole}>
                {humanize(user.role)}
                {user.home_department ? ` · ${user.home_department}` : ""} · {scope}
              </span>
            </div>
            <button
              type="button"
              role="menuitem"
              className={styles.menuItem}
              disabled={signingOut}
              onClick={() => {
                setSigningOut(true);
                logout().finally(() => setSigningOut(false));
              }}
            >
              {signingOut ? <Spinner /> : <LogOut aria-hidden="true" />}
              {signingOut ? "Signing out…" : "Sign out"}
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export default function TopBar() {
  const { user, logout } = useAuth();
  const items = useNavItems(user);
  const openAlerts = useOpenAlerts();
  const openCount = openAlerts.data?.length ?? 0;
  const [mobileOpen, setMobileOpen] = useState(false);
  const setWorkspaceOpen = useUiStore((state) => state.setWorkspaceOpen);
  const workspaceOpen = useUiStore((state) => state.workspaceOpen);
  const { pathname } = useLocation();

  useEffect(() => setMobileOpen(false), [pathname]);

  return (
    <header className={styles.topbar}>
      <NavLink to="/live" className={styles.brand} aria-label="Sentinel home">
        <SentinelMark size={28} />
        <span className={styles.brandName}>Sentinel</span>
      </NavLink>

      <nav className={styles.nav} aria-label="Primary">
        <NavItems items={items} openAlerts={openCount} />
      </nav>

      <div className={styles.topbarAside}>
        <EstateStatus />
        <SoundToggle />
        <IconButton label="Workspace" className={styles.mobileOnly} aria-pressed={workspaceOpen} onClick={() => setWorkspaceOpen(!workspaceOpen)}>
          <Layers />
        </IconButton>
        <IconButton label="Menu" className={styles.menuButton} aria-expanded={mobileOpen} onClick={() => setMobileOpen(!mobileOpen)}>
          <Menu />
        </IconButton>
        <UserMenu user={user} logout={logout} />
      </div>

      <AnimatePresence>
        {mobileOpen && (
          <motion.nav
            className={styles.mobileNav}
            aria-label="Primary"
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8, transition: { duration: 0.12 } }}
          >
            <NavItems items={items} openAlerts={openCount} vertical onNavigate={() => setMobileOpen(false)} />
          </motion.nav>
        )}
      </AnimatePresence>
    </header>
  );
}
