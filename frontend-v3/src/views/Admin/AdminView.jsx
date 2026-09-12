import { useCallback, useEffect, useState } from "react";

import { api } from "../../api.js";
import { useToast } from "../../components/Toast.jsx";
import { isSuperAdmin, useAuth } from "../../context/AuthContext.jsx";
import { useDepartments } from "../../context/DepartmentsContext.jsx";
import { useGsapReveal } from "../../hooks/useGsapReveal.js";
import { usePageTitle } from "../../hooks/usePageTitle.js";

function title(value) {
  return value.replaceAll("_", " ");
}

// The registered base_url is a live credentialed endpoint reference --
// shown host-only in the list (never the full path/query), the same
// "structural info yes, raw endpoint no" line CameraOut already draws for
// stream URLs. Falls back to the raw string only if it somehow isn't a
// parseable URL, so this never throws on an odd value.
function maskUrl(url) {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

const AUDIT_PAGE_SIZE = 25;
const NEW_SOURCE_DRAFT = {
  name: "", adapter: "sentinel_default", base_url: "", browser_base_url: "",
  auth_header_name: "", auth_secret: "", allow_private_host: false,
};

export default function AdminView() {
  usePageTitle("Access admin");
  const { user } = useAuth();
  const { departments, refresh: refreshDepartments } = useDepartments();
  const superAdmin = isSuperAdmin(user);
  const showToast = useToast();
  const [requests, setRequests] = useState([]);
  const [users, setUsers] = useState([]);
  const [audit, setAudit] = useState({ total: 0, events: [] });
  const [auditOffset, setAuditOffset] = useState(0);
  const [clearances, setClearances] = useState({});
  const [newDepartment, setNewDepartment] = useState("");
  const [newGrants, setNewGrants] = useState({});
  const [busy, setBusy] = useState(false);
  const [sources, setSources] = useState([]);
  const [newSource, setNewSource] = useState(NEW_SOURCE_DRAFT);
  const [demoMode, setDemoMode] = useState(null);
  const [demoBusy, setDemoBusy] = useState(false);
  const [governmentMode, setGovernmentMode] = useState(null);
  const [governmentBusy, setGovernmentBusy] = useState(false);
  const userListRef = useGsapReveal(".admin-user-card", { stagger: 0.06, duration: 0.4, y: 18, scale: true }, [users.length]);

  const load = useCallback(async () => {
    const [requestRows, userRows, auditPage, sourceRows, demoModeStatus, governmentModeStatus] = await Promise.all([
      api("/admin/registration-requests?request_status=pending"),
      api("/admin/users"),
      api(`/admin/audit-events?limit=${AUDIT_PAGE_SIZE}&offset=${auditOffset}`),
      superAdmin ? api("/catalogue-sources") : Promise.resolve([]),
      superAdmin ? api("/admin/demo-mode") : Promise.resolve(null),
      superAdmin ? api("/admin/government-mode") : Promise.resolve(null),
    ]);
    setRequests(requestRows);
    setUsers(userRows);
    setAudit(auditPage);
    setSources(sourceRows);
    setDemoMode(demoModeStatus);
    setGovernmentMode(governmentModeStatus);
  }, [auditOffset, superAdmin]);

  useEffect(() => {
    load().catch((error) => showToast("Admin data failed: " + error.message));
  }, [load, showToast]);

  async function perform(work, success) {
    setBusy(true);
    try {
      await work();
      await load();
      showToast(success);
    } catch (error) {
      showToast(error.message);
    } finally {
      setBusy(false);
    }
  }

  function approve(request) {
    const clearance = request.requested_role === "department_admin"
      ? "operator"
      : clearances[request.id] ?? "viewer";
    return perform(
      () => api(`/admin/registration-requests/${request.id}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ clearance }),
      }),
      `Approved ${request.full_name} as ${title(request.requested_role)}`,
    );
  }

  function reject(request) {
    const reason = window.prompt(`Reason for rejecting ${request.full_name}:`);
    if (!reason?.trim()) return;
    perform(
      () => api(`/admin/registration-requests/${request.id}/reject`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason }),
      }),
      `Rejected ${request.full_name}`,
    );
  }

  function setGrant(account, department, clearance) {
    perform(
      () => api(`/admin/users/${account.id}/grants/${encodeURIComponent(department)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ clearance }),
      }),
      `Updated ${account.full_name}'s ${department} access`,
    );
  }

  function revokeGrant(account, department) {
    perform(
      () => api(`/admin/users/${account.id}/grants/${encodeURIComponent(department)}`, { method: "DELETE" }),
      `Revoked ${department} access`,
    );
  }

  function addGrant(account, draft) {
    // Never silently no-op: if the draft somehow has no department the
    // operator gets told, rather than clicking a button that does nothing.
    if (!draft?.department) {
      showToast("Pick a department to grant first.");
      return;
    }
    setGrant(account, draft.department, draft.clearance ?? "viewer");
  }

  function setGrantDraft(accountId, field, value) {
    setNewGrants((current) => ({
      ...current,
      [accountId]: { clearance: "viewer", ...current[accountId], [field]: value },
    }));
  }

  function createDepartment(event) {
    event.preventDefault();
    const name = newDepartment.trim();
    if (!name) return;
    perform(async () => {
      await api("/admin/departments", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      setNewDepartment("");
      await refreshDepartments();
    }, `Created ${name}`);
  }

  function createSource(event) {
    event.preventDefault();
    const name = newSource.name.trim();
    const base_url = newSource.base_url.trim();
    if (!name || !base_url) {
      showToast("Name and base URL are both required.");
      return;
    }
    // auth_header_name/auth_secret are a pair or neither -- an empty string
    // means "not configured", not "clear this field" (this is create, not
    // update, so there's nothing to clear yet).
    const payload = {
      name,
      adapter: newSource.adapter,
      base_url,
      browser_base_url: newSource.browser_base_url.trim() || null,
      auth_header_name: newSource.auth_header_name.trim() || null,
      auth_secret: newSource.auth_secret.trim() || null,
      allow_private_host: newSource.allow_private_host,
    };
    perform(async () => {
      await api("/catalogue-sources", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      setNewSource(NEW_SOURCE_DRAFT);
    }, `Registered catalogue source "${name}"`);
  }

  // Not perform(): the success message depends on the sync result (how
  // many cameras were actually new/updated/gone), which perform's static
  // `success` string can't express -- an operator being told "3 new, 1
  // updated" tells them something a generic "Synced" toast doesn't.
  async function syncSource(source) {
    setBusy(true);
    try {
      const result = await api(`/catalogue-sources/${source.id}/sync`, { method: "POST" });
      await load();
      showToast(
        `${source.name}: ${result.inserted} new, ${result.updated} updated`
        + (result.disappeared.length ? `, ${result.disappeared.length} no longer listed` : ""),
      );
    } catch (error) {
      showToast(error.message);
    } finally {
      setBusy(false);
    }
  }

  function toggleSourceActive(source) {
    perform(
      () => api(`/catalogue-sources/${source.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ active: !source.active }),
      }),
      `${source.name} is now ${source.active ? "deactivated" : "active"}`,
    );
  }

  function deleteSource(source) {
    if (!window.confirm(`Delete catalogue source "${source.name}"? This only works if no cameras still reference it.`)) return;
    perform(
      () => api(`/catalogue-sources/${source.id}`, { method: "DELETE" }),
      `Deleted "${source.name}"`,
    );
  }

  async function toggleDemoMode(enabled) {
    setDemoBusy(true);
    try {
      const status = await api("/admin/demo-mode/toggle", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
      });
      setDemoMode(status);
      showToast(enabled ? "Demo mode enabled" : "Demo mode disabled — rehearsal cameras and watchlist entry removed");
    } catch (error) {
      showToast(error.message);
    } finally {
      setDemoBusy(false);
    }
  }

  async function toggleGovernmentMode(enabled) {
    setGovernmentBusy(true);
    try {
      const status = await api("/admin/government-mode/toggle", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
      });
      setGovernmentMode(status);
      showToast(enabled ? "Government mode enabled" : "Government mode disabled — original stream URLs restored");
    } catch (error) {
      showToast(error.message);
    } finally {
      setGovernmentBusy(false);
    }
  }

  return (
    <section className="view active admin-view">
      <div className="admin-heading">
        <div>
          <h2>Access administration</h2>
          <p className="hint">
            {superAdmin
              ? "Approve any request, create departments, and manage cross-department grants."
              : `Approve employees and set clearance inside ${user.home_department}.`}
          </p>
        </div>
        {superAdmin && (
          <form className="toolbar" onSubmit={createDepartment}>
            <input
              required minLength={2} placeholder="New department"
              value={newDepartment} onChange={(event) => setNewDepartment(event.target.value)}
            />
            <button className="primary" disabled={busy}>Create</button>
          </form>
        )}
      </div>

      <h3>Pending registration requests</h3>
      {requests.length === 0 ? <p className="hint">No requests are waiting for your approval.</p> : (
        <div className="table-scroll"><table>
          <thead><tr><th>Applicant</th><th>Department</th><th>Requested role</th><th>Clearance</th><th>Submitted</th><th /></tr></thead>
          <tbody>{requests.map((request) => (
            <tr key={request.id}>
              <td><strong>{request.full_name}</strong><br /><small>{request.email}</small></td>
              <td>{request.requested_department}</td>
              <td>{title(request.requested_role)}</td>
              <td>
                {request.requested_role === "department_admin" ? "operator" : (
                  <select
                    value={clearances[request.id] ?? "viewer"}
                    onChange={(event) => setClearances((current) => ({ ...current, [request.id]: event.target.value }))}
                  >
                    <option value="viewer">viewer</option><option value="operator">operator</option>
                  </select>
                )}
              </td>
              <td>{new Date(request.created_at).toLocaleString()}</td>
              <td className="row-actions">
                <button className="link-btn" disabled={busy} onClick={() => approve(request)}>Approve</button>
                <button className="link-btn danger" disabled={busy} onClick={() => reject(request)}>Reject</button>
              </td>
            </tr>
          ))}</tbody>
        </table></div>
      )}

      {superAdmin && (
        <>
          <h3>Departments</h3>
          <div className="department-list">
            {departments.map((department) => {
              const members = users.filter((account) => account.home_department === department.name);
              const admins = members.filter((account) => account.role === "department_admin");
              const departmentUsers = members.filter((account) => account.role === "department_user");
              return (
                <details className="department-card" key={department.name}>
                  <summary>
                    <strong>{department.name}</strong>
                    <span className="department-card-counts">
                      {admins.length} admin{admins.length === 1 ? "" : "s"} · {departmentUsers.length} user{departmentUsers.length === 1 ? "" : "s"}
                    </span>
                  </summary>
                  {members.length === 0 ? (
                    <p className="hint">No approved members yet.</p>
                  ) : (
                    <table className="department-members-table">
                      <thead><tr><th>Name</th><th>Role</th><th>Home clearance</th><th>Status</th></tr></thead>
                      <tbody>{members.map((account) => {
                        const homeGrant = account.grants.find((grant) => grant.is_home);
                        return (
                          <tr key={account.id}>
                            <td><strong>{account.full_name}</strong><br /><small>{account.email}</small></td>
                            <td>{title(account.role)}</td>
                            <td>{homeGrant?.clearance ?? "—"}</td>
                            <td><span className={`badge ${account.status === "active" ? "badge-ok" : "badge-bad"}`}>{account.status}</span></td>
                          </tr>
                        );
                      })}</tbody>
                    </table>
                  )}
                </details>
              );
            })}
          </div>
        </>
      )}

      {superAdmin && (
        <>
          <h3>Catalogue sources</h3>
          <p className="hint">
            Named, credentialed camera catalogues beyond the official sandbox feed (which stays configured separately
            and is unaffected by anything here). A source's URL and credential are never shown again once saved.
          </p>
          {sources.length === 0 ? (
            <p className="hint">No additional catalogue sources registered yet.</p>
          ) : (
            <div className="table-scroll"><table>
              <thead><tr><th>Name</th><th>Adapter</th><th>Host</th><th>Status</th><th>Last synced</th><th /></tr></thead>
              <tbody>{sources.map((source) => (
                <tr key={source.id}>
                  <td><strong>{source.name}</strong></td>
                  <td>{source.adapter}</td>
                  <td>{maskUrl(source.base_url)}</td>
                  <td><span className={`badge ${source.active ? "badge-ok" : "badge-bad"}`}>{source.active ? "active" : "deactivated"}</span></td>
                  <td>
                    {source.last_synced_at ? new Date(source.last_synced_at).toLocaleString() : "never"}
                    {source.last_sync_result && (
                      <>
                        <br />
                        <small className="hint">
                          {source.last_sync_result.inserted} new · {source.last_sync_result.updated} updated
                          {source.last_sync_result.disappeared?.length
                            ? ` · ${source.last_sync_result.disappeared.length} gone`
                            : ""}
                        </small>
                      </>
                    )}
                  </td>
                  <td className="row-actions">
                    <button className="link-btn" disabled={busy || !source.active} onClick={() => syncSource(source)}>Sync now</button>
                    <button className="link-btn" disabled={busy} onClick={() => toggleSourceActive(source)}>
                      {source.active ? "Deactivate" : "Activate"}
                    </button>
                    <button className="link-btn danger" disabled={busy} onClick={() => deleteSource(source)}>Delete</button>
                  </td>
                </tr>
              ))}</tbody>
            </table></div>
          )}

          <form className="admin-source-form" onSubmit={createSource}>
            <h4 className="grant-heading">Register a source</h4>
            <div className="admin-source-form-grid">
              <input
                required placeholder="Name (e.g. Live Corp)"
                value={newSource.name} onChange={(event) => setNewSource((c) => ({ ...c, name: event.target.value }))}
              />
              <select
                value={newSource.adapter}
                onChange={(event) => setNewSource((c) => ({ ...c, adapter: event.target.value }))}
              >
                <option value="sentinel_default">sentinel_default</option>
              </select>
              <input
                required type="url" placeholder="Catalogue base URL"
                value={newSource.base_url} onChange={(event) => setNewSource((c) => ({ ...c, base_url: event.target.value }))}
              />
              <input
                placeholder="Browser base URL (optional, resolves relative HLS paths)"
                value={newSource.browser_base_url}
                onChange={(event) => setNewSource((c) => ({ ...c, browser_base_url: event.target.value }))}
              />
              <input
                placeholder="Auth header name (optional, e.g. X-Api-Key)"
                value={newSource.auth_header_name}
                onChange={(event) => setNewSource((c) => ({ ...c, auth_header_name: event.target.value }))}
              />
              <input
                type="password" placeholder="Auth secret (optional)"
                value={newSource.auth_secret} onChange={(event) => setNewSource((c) => ({ ...c, auth_secret: event.target.value }))}
              />
            </div>
            <label className="admin-source-checkbox" title="Only enable for a local/test catalogue -- a public source should never need this.">
              <input
                type="checkbox" checked={newSource.allow_private_host}
                onChange={(event) => setNewSource((c) => ({ ...c, allow_private_host: event.target.checked }))}
              />
              Allow a private/loopback host (local testing only)
            </label>
            <button className="primary" disabled={busy}>Register source</button>
          </form>
        </>
      )}

      <h3>Users and department grants</h3>
      <div ref={userListRef} className="admin-user-list">
        {users.map((account) => {
          const available = departments.filter((department) => !account.grants.some((grant) => grant.department === department.name));
          // Merged over the defaults, not substituted for them. Previously
          // `newGrants[account.id] ?? {defaults}` meant that touching the
          // *clearance* dropdown first stored {clearance} with no department
          // key -- the department <select> then had value={undefined}, went
          // uncontrolled, and still *looked* like the first option was
          // chosen while the state said otherwise. Add grant then read an
          // undefined department and returned silently. That was the
          // "Add grant doesn't work" bug: it depended on which dropdown you
          // touched first.
          const draft = { department: available[0]?.name ?? "", clearance: "viewer", ...newGrants[account.id] };
          return (
            <article
              className={`admin-user-card${account.status === "active" ? "" : " admin-user-card-off"}`}
              key={account.id}
            >
              {/* Identity band. Role sits in the label face rather than a
                  grey pill: it's the most consequential thing about an
                  account, and colour isn't available to mark it (colour is
                  reserved for urgency -- DESIGN.md §4). */}
              <header className="admin-user-title">
                <div className="admin-user-ident">
                  <strong>{account.full_name}</strong>
                  <span className="admin-user-role">{title(account.role)}</span>
                  <small>{account.email}</small>
                </div>
                <div className="admin-user-state">
                  {/* Status was previously only inferable from the button's
                      label, so a disabled account looked identical to an
                      active one when scanning the list. Stated outright, and
                      matching how the department directory already shows it. */}
                  {account.status !== "active" && <span className="badge badge-bad">disabled</span>}
                  <button
                    className="secondary" disabled={busy || account.id === user.id}
                    title={account.id === user.id ? "You cannot change your own account status" : undefined}
                    onClick={() => perform(
                      () => api(`/admin/users/${account.id}/status`, {
                        method: "PUT", headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ status: account.status === "active" ? "disabled" : "active" }),
                      }),
                      `${account.full_name} is now ${account.status === "active" ? "disabled" : "active"}`,
                    )}
                  >{account.status === "active" ? "Disable" : "Enable"}</button>
                </div>
              </header>

              <div className="grant-block">
                <h4 className="grant-heading">Department access</h4>
                {account.grants.length === 0 ? (
                  /* A super admin holds no per-department grants -- their
                     access is global -- so this rendered as an empty gap
                     that read like a control which had failed to load. */
                  <p className="hint grant-empty">
                    {account.role === "super_admin"
                      ? "Global — every department, by role."
                      : "None yet."}
                  </p>
                ) : (
                  <div className="grant-list">
                    {account.grants.map((grant) => (
                      /* display:contents on the row, so every cell joins the
                         one grid on .grant-list and the clearance selects line
                         up down the card. Each row was its own flex container
                         before, so the selects landed wherever the department
                         name happened to end. */
                      <div className="grant-row" key={grant.department}>
                        <span className="grant-dept">
                          {grant.department}
                          {grant.is_home && <span className="grant-home">home</span>}
                        </span>
                        <select
                          aria-label={`${grant.department} clearance`}
                          value={grant.clearance} disabled={busy}
                          onChange={(event) => setGrant(account, grant.department, event.target.value)}
                        >
                          <option value="viewer">viewer</option><option value="operator">operator</option>
                        </select>
                        {superAdmin && !grant.is_home ? (
                          <button className="link-btn danger" disabled={busy} onClick={() => revokeGrant(account, grant.department)}>
                            Revoke
                          </button>
                        ) : (
                          /* Holds the column open so a home grant's select
                             stays aligned with the revocable ones above it. */
                          <span aria-hidden="true" />
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {superAdmin && available.length > 0 && account.role !== "super_admin" && (
                <div className="grant-add">
                  <h4 className="grant-heading">Grant another department</h4>
                  <div className="grant-add-controls">
                    <select
                      aria-label="Department to grant"
                      value={draft.department}
                      onChange={(event) => setGrantDraft(account.id, "department", event.target.value)}
                    >
                      {available.map((department) => (
                        <option key={department.name} value={department.name}>{department.name}</option>
                      ))}
                    </select>
                    <select
                      aria-label="Clearance to grant"
                      value={draft.clearance}
                      onChange={(event) => setGrantDraft(account.id, "clearance", event.target.value)}
                    >
                      <option value="viewer">viewer</option><option value="operator">operator</option>
                    </select>
                    <button className="secondary" disabled={busy} onClick={() => addGrant(account, draft)}>Add grant</button>
                  </div>
                </div>
              )}
            </article>
          );
        })}
      </div>

      <h3>Access audit</h3>
      <p className="hint">
        {superAdmin
          ? "Every recorded action, newest first."
          : `Actions in ${user.home_department}, plus your own — including any that carry no department, such as sign-ins.`}
      </p>
      <div className="table-scroll"><table>
        <thead><tr><th>Time</th><th>Actor</th><th>Action</th><th>Department</th><th>Result</th></tr></thead>
        <tbody>{audit.events.map((event) => (
          <tr key={event.id}>
            <td>{new Date(event.occurred_at).toLocaleString()}</td><td>{event.actor_email ?? "system"}</td>
            <td>{event.action}</td><td>{event.department ?? "—"}</td>
            <td><span className={`badge ${event.result === "success" ? "badge-ok" : "badge-bad"}`}>{event.result}</span></td>
          </tr>
        ))}</tbody>
      </table></div>
      {audit.events.length === 0 && <p className="hint">No audit events recorded yet.</p>}
      {audit.total > AUDIT_PAGE_SIZE && (
        <div className="audit-pager">
          <button
            className="secondary" disabled={auditOffset === 0}
            onClick={() => setAuditOffset((current) => Math.max(0, current - AUDIT_PAGE_SIZE))}
          >Newer</button>
          <span className="hint">
            {auditOffset + 1}–{Math.min(auditOffset + AUDIT_PAGE_SIZE, audit.total)} of {audit.total}
          </span>
          <button
            className="secondary" disabled={auditOffset + AUDIT_PAGE_SIZE >= audit.total}
            onClick={() => setAuditOffset((current) => current + AUDIT_PAGE_SIZE)}
          >Older</button>
        </div>
      )}

      {superAdmin && (
        <details className="admin-advanced">
          <summary>Advanced</summary>
          <div className="admin-advanced-row">
            <div>
              <strong>Demo mode</strong>
              <p className="hint">
                Stands up a rehearsal environment for a screen recording: onboards a small set of cameras backed by
                looping synthetic footage, a matching watchlist entry, and a plate's prior stops, all through the
                same code paths real onboarding and ANPR use. Turning this off removes everything it created and
                leaves the rest of the registry untouched.
              </p>
              {demoMode?.enabled && (
                <p className="hint">
                  Active since {new Date(demoMode.activated_at).toLocaleString()} — {demoMode.camera_count} camera(s), plate {demoMode.plate}.
                </p>
              )}
            </div>
            <label className="switch" title={demoMode?.enabled ? "Turn demo mode off" : "Turn demo mode on"}>
              <input
                type="checkbox"
                checked={!!demoMode?.enabled}
                disabled={demoBusy || demoMode === null}
                onChange={(event) => toggleDemoMode(event.target.checked)}
              />
            </label>
          </div>

          <div className="admin-advanced-row">
            <div>
              <strong>Government mode</strong>
              <p className="hint">
                The mirror image of demo mode: shows only real catalogue-provided cameras (nothing this app itself
                created), and replaces any of their streams with the matching completed recording from{" "}
                <code>recorded-streams/</code> (record_live_clips.py's own output — the camera_id comes from each
                clip's .json sidecar) — the real government feed unchanged everywhere else, ANPR and every other
                analytics mode included. Turning this off restores the original stream URLs. Mutually exclusive
                with demo mode.
              </p>
              {governmentMode?.enabled && (
                <p className="hint">
                  Active since {new Date(governmentMode.activated_at).toLocaleString()} — camera(s): {governmentMode.camera_ids.join(", ")}.
                </p>
              )}
            </div>
            <label className="switch" title={governmentMode?.enabled ? "Turn government mode off" : "Turn government mode on"}>
              <input
                type="checkbox"
                checked={!!governmentMode?.enabled}
                disabled={governmentBusy || governmentMode === null}
                onChange={(event) => toggleGovernmentMode(event.target.checked)}
              />
            </label>
          </div>
        </details>
      )}
    </section>
  );
}
