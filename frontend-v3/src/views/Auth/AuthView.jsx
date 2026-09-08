import { useEffect, useState } from "react";

import { api } from "../../api.js";
import SentinelMark from "../../components/SentinelMark.jsx";
import { useAuth } from "../../context/AuthContext.jsx";
import { usePageTitle } from "../../hooks/usePageTitle.js";

// Mirrors the server's own rule (auth_schemas.py's RegistrationRequestIn:
// `min_length=10`). One constant so the input's validation and the hint that
// explains it can't drift apart -- the backend stays the enforcement point.
const PASSWORD_MIN_LENGTH = 10;

export default function AuthView() {
  const { login } = useAuth();
  const [mode, setMode] = useState("login");
  usePageTitle(mode === "login" ? "Sign in" : "Request access");
  const [departments, setDepartments] = useState([]);
  const [form, setForm] = useState({
    full_name: "", email: "", password: "", requested_department: "", requested_role: "department_user",
  });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
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
      .catch((error) => setMessage("Could not load departments: " + error.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode]);

  function set(field, value) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      if (mode === "login") {
        await login(form.email, form.password);
      } else {
        const result = await api("/registration-requests", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(form),
        });
        setMessage(`Request #${result.request_id} submitted. An administrator must approve it before login.`);
        setMode("login");
      }
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-page">
      <section className="auth-card">
        <div className="auth-brand">
          <SentinelMark size={30} />
          <span>
            Sentinel
            <span className="sub">Operator Console</span>
          </span>
        </div>
        <h1>{mode === "login" ? "Sign in" : "Request access"}</h1>
        <p className="hint">
          {mode === "login"
            ? "Every camera, stream, alert and administrative route requires an approved account."
            : "Employee requests go to the selected department admin; department-admin requests go to the super admin."}
        </p>
        <form onSubmit={submit}>
          {mode === "register" && (
            <div className="field">
              <label>Full name</label>
              <input required minLength={2} value={form.full_name} onChange={(e) => set("full_name", e.target.value)} />
            </div>
          )}
          <div className="field">
            <label>Email</label>
            <input required type="email" autoComplete="email" value={form.email} onChange={(e) => set("email", e.target.value)} />
          </div>
          <div className="field">
            <label>Password</label>
            <div className="password-field">
              <input
                required type={showPassword ? "text" : "password"}
                minLength={mode === "register" ? PASSWORD_MIN_LENGTH : undefined}
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                value={form.password} onChange={(e) => set("password", e.target.value)}
              />
              <button
                type="button"
                className="link-btn password-toggle"
                onClick={() => setShowPassword((current) => !current)}
                aria-label={showPassword ? "Hide password" : "Show password"}
              >
                {showPassword ? "Hide" : "Show"}
              </button>
            </div>
            {/* Shown only once there is something to judge and it falls
                short: silent on an untouched field, silent again as soon as
                the rule is met. Keying this on `mode` alone left it on
                screen permanently; keying it on length alone still greeted
                an empty form with a complaint about input nobody had
                entered yet. */}
            {mode === "register" && form.password.length > 0
              && form.password.length < PASSWORD_MIN_LENGTH && (
              <div className="hint hint-warn">
                {PASSWORD_MIN_LENGTH - form.password.length} more character
                {PASSWORD_MIN_LENGTH - form.password.length === 1 ? "" : "s"} needed.
              </div>
            )}
          </div>
          {mode === "register" && (
            <>
              <div className="field">
                <label>Home department</label>
                <select required value={form.requested_department} onChange={(e) => set("requested_department", e.target.value)}>
                  {departments.map((department) => <option key={department.name}>{department.name}</option>)}
                </select>
              </div>
              <div className="field">
                <label>Account type</label>
                <select value={form.requested_role} onChange={(e) => set("requested_role", e.target.value)}>
                  <option value="department_user">Department employee</option>
                  <option value="department_admin">Department administrator</option>
                </select>
              </div>
            </>
          )}
          {message && <div className="auth-message">{message}</div>}
          <button className="primary auth-submit" disabled={busy}>
            {busy ? "Please wait…" : mode === "login" ? "Sign in" : "Submit request"}
          </button>
        </form>
        <button className="link-btn auth-switch" onClick={() => { setMode(mode === "login" ? "register" : "login"); setMessage(""); }}>
          {mode === "login" ? "Need an account? Request access" : "Already approved? Sign in"}
        </button>
      </section>
    </div>
  );
}
