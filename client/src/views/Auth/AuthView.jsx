import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import gsap from "gsap";
import {
  ArrowLeft,
  Camera,
  Car,
  MapPinned,
  Moon,
  Radar,
  Shield,
  Sun,
} from "lucide-react";

import { api } from "../../api.js";
import BrandMark from "../../components/BrandMark.jsx";
import { useAuth } from "../../context/AuthContext.jsx";
import { useTheme } from "../../context/ThemeContext.jsx";
import { usePageTitle } from "../../hooks/usePageTitle.js";

const PASSWORD_MIN_LENGTH = 10;

const PILLARS = [
  { icon: Camera, label: "Cameras" },
  { icon: Car, label: "Plates" },
  { icon: MapPinned, label: "Routes" },
  { icon: Shield, label: "Clearance" },
];

const STREAM_PLATES = [
  "DL 01 CX 8820",
  "MH 12 AB 4291",
  "KA 05 MN 1134",
  "TN 09 BK 7702",
  "GJ 18 RP 3301",
  "UP 32 KT 5510",
  "RJ 14 QW 9088",
  "WB 06 HL 2145",
];

export default function AuthView() {
  const { login } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const isLight = theme === "light";
  const [searchParams] = useSearchParams();
  const [mode, setMode] = useState(() =>
    searchParams.get("mode") === "register" ? "register" : "login",
  );
  usePageTitle(mode === "login" ? "Sign in" : "Request access");

  const rootRef = useRef(null);

  useEffect(() => {
    const q = searchParams.get("mode");
    if (q === "register" || q === "login") setMode(q);
  }, [searchParams]);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const ctx = gsap.context(() => {
      gsap.from(".auth-shell-brand > *", { y: 16, opacity: 0, stagger: 0.06, duration: 0.45, ease: "power3.out" });
      gsap.from(".auth-shell-card", { y: 22, opacity: 0, duration: 0.55, delay: 0.12, ease: "power3.out" });
      gsap.from(".auth-shell-pillars span", { y: 10, opacity: 0, stagger: 0.05, duration: 0.35, delay: 0.25 });
      gsap.to(".auth-radar-sweep", { rotate: 360, duration: 8, repeat: -1, ease: "none" });
      gsap.to(".auth-ring-a", { rotate: 360, duration: 48, repeat: -1, ease: "none" });
      gsap.to(".auth-ring-b", { rotate: -360, duration: 64, repeat: -1, ease: "none" });
    }, root);
    return () => ctx.revert();
  }, []);

  const [departments, setDepartments] = useState([]);
  const [form, setForm] = useState({
    full_name: "",
    email: "",
    password: "",
    requested_department: "",
    requested_role: "department_user",
  });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [messageOk, setMessageOk] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  useEffect(() => {
    if (mode !== "register") return;
    api("/auth/registration-options")
      .then((rows) => {
        setDepartments(rows);
        if (!form.requested_department && rows[0]) {
          setForm((current) => ({ ...current, requested_department: rows[0].name }));
        }
      })
      .catch((error) => {
        setMessageOk(false);
        setMessage("Could not load departments: " + error.message);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode]);

  function set(field, value) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  function switchMode(next) {
    setMode(next);
    setMessage("");
    setMessageOk(false);
  }

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    setMessageOk(false);
    try {
      if (mode === "login") {
        await login(form.email, form.password);
      } else {
        const result = await api("/registration-requests", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(form),
        });
        setMessageOk(true);
        setMessage(
          `Request #${result.request_id} submitted. An administrator must approve it before login.`,
        );
        setMode("login");
      }
    } catch (error) {
      setMessageOk(false);
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-shell" ref={rootRef}>
      {/* Cyber / city pattern backdrop — no map */}
      <div className="auth-fx" aria-hidden="true">
        <div className="auth-fx-base" />
        <div className="auth-fx-grid" />
        <div className="auth-fx-roads">
          <span /><span /><span /><span />
        </div>
        <div className="auth-fx-radar">
          <div className="auth-radar-ring" />
          <div className="auth-radar-ring auth-radar-ring-2" />
          <div className="auth-radar-sweep" />
          <div className="auth-radar-core" />
        </div>
        <div className="auth-fx-orbit">
          <div className="auth-ring-a">
            <i style={{ "--a": 0 }}><Camera size={14} /></i>
            <i style={{ "--a": 1 }}><Car size={14} /></i>
            <i style={{ "--a": 2 }}><MapPinned size={14} /></i>
            <i style={{ "--a": 3 }}><Shield size={14} /></i>
          </div>
          <div className="auth-ring-b">
            <i style={{ "--a": 0 }}><Radar size={13} /></i>
            <i style={{ "--a": 1 }}><Camera size={13} /></i>
            <i style={{ "--a": 2 }}><Car size={13} /></i>
            <i style={{ "--a": 3 }}><Shield size={13} /></i>
          </div>
        </div>
        <div className="auth-fx-stream">
          <div className="auth-fx-stream-track">
            {[...STREAM_PLATES, ...STREAM_PLATES].map((p, i) => (
              <span key={`${p}-${i}`}>{p}</span>
            ))}
          </div>
        </div>
        <div className="auth-fx-orbs">
          <span className="auth-orb auth-orb-a" />
          <span className="auth-orb auth-orb-b" />
          <span className="auth-orb auth-orb-c" />
        </div>
      </div>

      <header className="auth-shell-top">
        <Link to="/" className="auth-shell-logo">
          <BrandMark size={28} />
          <span>
            CityTraceAI
            <small>Urban ANPR platform</small>
          </span>
        </Link>
        <div className="auth-shell-top-actions">
          <button
            type="button"
            className="auth-shell-icon-btn"
            onClick={toggleTheme}
            title={isLight ? "Switch to dark mode" : "Switch to light mode"}
            aria-label={isLight ? "Switch to dark mode" : "Switch to light mode"}
          >
            {isLight ? <Moon size={16} strokeWidth={2} /> : <Sun size={16} strokeWidth={2} />}
          </button>
          <Link to="/" className="auth-shell-back">
            <ArrowLeft size={14} strokeWidth={2.25} />
            Home
          </Link>
        </div>
      </header>

      <main className="auth-shell-main">
        <section className="auth-shell-brand">
          <p className="auth-shell-eyebrow">
            <Radar size={14} strokeWidth={2} />
            Restricted console · Authorised operators
          </p>
          <h1>
            Command the city.
            <span> Authenticate to enter.</span>
          </h1>
          <p className="auth-shell-lead">
            Live cameras, plate reads, road networks, and watchlist intelligence —
            one clearance gate for the duty desk.
          </p>
          <div className="auth-shell-pillars">
            {PILLARS.map(({ icon: Icon, label }) => (
              <span key={label}>
                <Icon size={15} strokeWidth={2} />
                {label}
              </span>
            ))}
          </div>
        </section>

        <section className="auth-shell-card" aria-label="Authentication">
          <div className="auth-shell-tabs" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={mode === "login"}
              className={mode === "login" ? "is-active" : undefined}
              onClick={() => switchMode("login")}
            >
              Sign in
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === "register"}
              className={mode === "register" ? "is-active" : undefined}
              onClick={() => switchMode("register")}
            >
              Request access
            </button>
          </div>

          <h2>{mode === "login" ? "Welcome back" : "Request access"}</h2>
          <p className="auth-shell-sub">
            {mode === "login"
              ? "Use your approved department credentials to open the operator console."
              : "Submit a request for review. Employee requests go to department admin; admin requests to super admin."}
          </p>

          <form className="auth-shell-form" onSubmit={submit} noValidate>
            {mode === "register" && (
              <label className="auth-field">
                <span>Full name</span>
                <input
                  required
                  autoComplete="name"
                  value={form.full_name}
                  onChange={(e) => set("full_name", e.target.value)}
                  placeholder="Operator name"
                />
              </label>
            )}

            <label className="auth-field">
              <span>Email</span>
              <input
                type="email"
                required
                autoComplete="username"
                value={form.email}
                onChange={(e) => set("email", e.target.value)}
                placeholder="you@department.gov"
              />
            </label>

            <label className="auth-field">
              <span>Password</span>
              <div className="auth-password">
                <input
                  type={showPassword ? "text" : "password"}
                  required
                  minLength={mode === "register" ? PASSWORD_MIN_LENGTH : undefined}
                  autoComplete={mode === "login" ? "current-password" : "new-password"}
                  value={form.password}
                  onChange={(e) => set("password", e.target.value)}
                  placeholder={mode === "register" ? `At least ${PASSWORD_MIN_LENGTH} characters` : "••••••••••••"}
                />
                <button type="button" onClick={() => setShowPassword((v) => !v)}>
                  {showPassword ? "Hide" : "Show"}
                </button>
              </div>
            </label>

            {mode === "register" && (
              <div className="auth-shell-form-row">
                <label className="auth-field">
                  <span>Department</span>
                  <select
                    required
                    value={form.requested_department}
                    onChange={(e) => set("requested_department", e.target.value)}
                  >
                    <option value="" disabled>
                      Select department
                    </option>
                    {departments.map((d) => (
                      <option key={d.name} value={d.name}>
                        {d.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="auth-field">
                  <span>Requested role</span>
                  <select
                    required
                    value={form.requested_role}
                    onChange={(e) => set("requested_role", e.target.value)}
                  >
                    <option value="department_user">Department user</option>
                    <option value="department_admin">Department admin</option>
                  </select>
                </label>
              </div>
            )}

            {message && (
              <div className={`auth-shell-msg ${messageOk ? "is-ok" : "is-err"}`} role="status">
                {message}
              </div>
            )}

            <button type="submit" className="auth-shell-submit" disabled={busy}>
              {busy
                ? mode === "login"
                  ? "Signing in…"
                  : "Submitting…"
                : mode === "login"
                  ? "Enter console"
                  : "Submit request"}
            </button>
          </form>

          <p className="auth-shell-legal">
            Restricted system for authorised law-enforcement and government operators.
          </p>
        </section>
      </main>
    </div>
  );
}
