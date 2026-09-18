import { useQuery } from "@tanstack/react-query";
import { Eye, EyeOff } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useState } from "react";

import { Button, Field, Input, Notice, Segmented, Select } from "../../components/ui.jsx";
import SentinelMark from "../../components/SentinelMark.jsx";
import { api } from "../../lib/api/client.js";
import { usePageTitle } from "../../lib/hooks.js";
import { useAuth } from "./AuthProvider.jsx";
import styles from "./SignIn.module.css";

// Mirrors the server's own rule (RegistrationRequestIn min_length=10).
const PASSWORD_MIN_LENGTH = 10;

// Optional sign-in backdrop, served from frontend-v5/public/images/. The page
// is complete without it; the first file that loads is faded in behind a
// blur and tint.
const BACKDROP_CANDIDATES = ["/images/signin-backdrop.webp", "/images/signin-backdrop.jpg"];

function useBackdrop() {
  const [src, setSrc] = useState(null);
  useEffect(() => {
    let cancelled = false;
    const tryAt = (index) => {
      if (index >= BACKDROP_CANDIDATES.length) return;
      const image = new Image();
      image.decoding = "async";
      image.onload = () => !cancelled && setSrc(BACKDROP_CANDIDATES[index]);
      image.onerror = () => !cancelled && tryAt(index + 1);
      image.src = BACKDROP_CANDIDATES[index];
    };
    tryAt(0);
    return () => {
      cancelled = true;
    };
  }, []);
  return src;
}

export default function SignInView() {
  const { login } = useAuth();
  const backdrop = useBackdrop();
  const [mode, setMode] = useState("login");
  usePageTitle(mode === "login" ? "Sign in" : "Request access");
  const [form, setForm] = useState({
    full_name: "",
    email: "",
    password: "",
    requested_department: "",
    requested_role: "department_user",
  });
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(null);

  const departments = useQuery({
    queryKey: ["registration-options"],
    queryFn: () => api("/auth/registration-options"),
    enabled: mode === "register",
    staleTime: 60_000,
  });

  const set = (field, value) => setForm((current) => ({ ...current, [field]: value }));

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      if (mode === "login") {
        await login(form.email, form.password);
      } else {
        const payload = { ...form, requested_department: form.requested_department || departments.data?.[0]?.name };
        const result = await api("/registration-requests", { method: "POST", json: payload });
        setMessage({ tone: "signal", text: `Request #${result.request_id} submitted. An administrator must approve it before you can sign in.` });
        setMode("login");
      }
    } catch (error) {
      setMessage({ tone: "critical", text: mode === "login" && error.status === 401 ? "That email and password don't match an approved account." : error.message });
    } finally {
      setBusy(false);
    }
  }

  const shortPassword = mode === "register" && form.password.length > 0 && form.password.length < PASSWORD_MIN_LENGTH;

  return (
    <div className={styles.page} data-backdrop={backdrop ? "true" : undefined}>
      <div
        className={styles.backdrop}
        style={backdrop ? { backgroundImage: `url("${backdrop}")` } : undefined}
        aria-hidden="true"
      />
      <div className={styles.brandPane}>
        <div className={styles.brand}>
          <SentinelMark size={36} />
          <span>Sentinel</span>
        </div>
        <div className={styles.pitch}>
          <h1>The city&apos;s cameras, and what they see.</h1>
          <p>
            Live video, plate recognition, person and suspicious-activity detection, watchlist alerts and vehicle
            journeys across cameras — in one console.
          </p>
        </div>
        <p className={styles.legal}>Authorised personnel only. Access is logged.</p>
      </div>

      <main className={styles.formPane}>
        <motion.section className={styles.card} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}>
          <Segmented
            label="Account"

            value={mode}
            onChange={(value) => {
              setMode(value);
              setMessage(null);
            }}
            options={[
              { value: "login", label: "Sign in" },
              { value: "register", label: "Request access" },
            ]}
          />
          <div>
            <h2>{mode === "login" ? "Welcome back" : "Request an account"}</h2>
            <p className={styles.lead}>
              {mode === "login"
                ? "Sign in with your approved operator account."
                : "Requests go to your department administrator; administrator requests go to the super admin."}
            </p>
          </div>

          <form className={styles.form} onSubmit={submit}>
            <AnimatePresence initial={false}>
              {mode === "register" && (
                <motion.div key="name" initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }}>
                  <Field label="Full name" htmlFor="full_name">
                    <Input id="full_name" required minLength={2} value={form.full_name} onChange={(e) => set("full_name", e.target.value)} autoComplete="name" />
                  </Field>
                </motion.div>
              )}
            </AnimatePresence>
            <Field label="Email" htmlFor="email">
              <Input id="email" type="email" required autoComplete="email" value={form.email} onChange={(e) => set("email", e.target.value)} autoFocus />
            </Field>
            <Field
              label="Password"
              htmlFor="password"
              error={shortPassword ? `${PASSWORD_MIN_LENGTH - form.password.length} more character${PASSWORD_MIN_LENGTH - form.password.length === 1 ? "" : "s"} needed` : null}
            >
              <div className={styles.password}>
                <Input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  required
                  minLength={mode === "register" ? PASSWORD_MIN_LENGTH : undefined}
                  autoComplete={mode === "login" ? "current-password" : "new-password"}
                  value={form.password}
                  onChange={(e) => set("password", e.target.value)}
                />
                <button type="button" className={styles.reveal} onClick={() => setShowPassword(!showPassword)} aria-label={showPassword ? "Hide password" : "Show password"}>
                  {showPassword ? <EyeOff /> : <Eye />}
                </button>
              </div>
            </Field>
            {mode === "register" && (
              <div className="ui-grid-2">
                <Field label="Home department" htmlFor="department">
                  <Select id="department" required value={form.requested_department || departments.data?.[0]?.name || ""} onChange={(e) => set("requested_department", e.target.value)}>
                    {(departments.data ?? []).map((department) => (
                      <option key={department.name} value={department.name}>
                        {department.name}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="Account type" htmlFor="role">
                  <Select id="role" value={form.requested_role} onChange={(e) => set("requested_role", e.target.value)}>
                    <option value="department_user">Department employee</option>
                    <option value="department_admin">Department administrator</option>
                  </Select>
                </Field>
              </div>
            )}
            {message && <Notice tone={message.tone}>{message.text}</Notice>}
            <Button type="submit" variant="primary" size="lg" loading={busy} className={styles.submit}>
              {mode === "login" ? "Sign in" : "Submit request"}
            </Button>
          </form>
        </motion.section>
      </main>
    </div>
  );
}
