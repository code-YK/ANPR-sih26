import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Archive, Database, Download, Film, KeyRound, Search } from "lucide-react";


import { API, api } from "../../api.js";
import { useConfirm } from "../../components/ConfirmDialog.jsx";
import { useToast } from "../../components/Toast.jsx";
import { isSuperAdmin, useAuth } from "../../context/AuthContext.jsx";
import { useCameras } from "../../context/CamerasContext.jsx";
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
  usePageTitle("Admin");
  const { user } = useAuth();
  const { departments, refresh: refreshDepartments } = useDepartments();
  const { cameras } = useCameras();
  const superAdmin = isSuperAdmin(user);
  const [confirm, confirmDialog] = useConfirm();
  const [archiving, setArchiving] = useState(false);
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
  // The section is the URL, not component state: /admin/audit is a link that
  // opens the audit log, Back steps between sections instead of leaving Admin
  // entirely, and a reload stays where the operator was. An unknown or
  // not-permitted section falls back to People rather than rendering nothing.
  const location = useLocation();
  const navigate = useNavigate();
  const requestedTab = location.pathname.replace(/^\/admin\/?/, "").split("/")[0];
  const [peopleQuery, setPeopleQuery] = useState("");
  const [roleFilter, setRoleFilter] = useState("");
  const [auditQuery, setAuditQuery] = useState("");
  const [auditResultFilter, setAuditResultFilter] = useState("");
  const [showRegisterSource, setShowRegisterSource] = useState(false);
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

  async function deleteSource(source) {
    const ok = await confirm({
      title: `Delete catalogue source "${source.name}"?`,
      body: "This only works if no cameras still reference it. The deletion is recorded in the audit log.",
      confirmLabel: "Delete source",
      danger: true,
    });
    if (!ok) return;
    perform(
      () => api(`/catalogue-sources/${source.id}`, { method: "DELETE" }),
      `Deleted "${source.name}"`,
    );
  }

  // Writes a verifiable NDJSON snapshot plus its SHA-256 digest to the
  // configured retention mount (auth.py's archive endpoint). Separate from the
  // download on purpose: a browser download never writes server-side data, and
  // this never returns audit rows to the browser.
  async function archiveAudit() {
    const ok = await confirm({
      title: "Write an audit archive?",
      body: "A verifiable snapshot of every audit event is written to the retention mount, with its SHA-256 digest. Existing archives are never overwritten.",
      confirmLabel: "Write archive",
    });
    if (!ok) return;
    setArchiving(true);
    try {
      const result = await api("/admin/audit-events/archive", { method: "POST" });
      showToast(`Audit archive written: ${result.event_count} events`, {
        tone: "live",
        detail: `${result.archive_name} · sha256 ${String(result.sha256).slice(0, 16)}…`,
      });
    } catch (error) {
      showToast("Archive failed: " + error.message);
    } finally {
      setArchiving(false);
    }
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

  const filteredUsers = useMemo(() => {
    const needle = peopleQuery.trim().toLowerCase();
    return users.filter((account) => {
      if (roleFilter && account.role !== roleFilter) return false;
      if (!needle) return true;
      const hay = [account.full_name, account.email, account.role, account.home_department]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return hay.includes(needle);
    });
  }, [users, peopleQuery, roleFilter]);

  const filteredAudit = useMemo(() => {
    const needle = auditQuery.trim().toLowerCase();
    return (audit.events ?? []).filter((event) => {
      if (auditResultFilter && event.result !== auditResultFilter) return false;
      if (!needle) return true;
      const hay = [event.actor_email, event.action, event.department, event.result]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return hay.includes(needle);
    });
  }, [audit.events, auditQuery, auditResultFilter]);

  function userInitials(account) {
    const name = (account.full_name || account.email || "??").trim();
    const parts = name.split(/\s+/).filter(Boolean);
    if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
    return name.slice(0, 2).toUpperCase();
  }

  function accessLabel(account) {
    if (account.role === "super_admin") return "All departments";
    if (!account.grants?.length) return "—";
    return account.grants.map((g) => g.department).join(", ");
  }

  function camerasInDept(name) {
    return (cameras ?? []).filter((c) => c.department === name).length;
  }

  const tabs = [
    { id: "people", label: "People" },
    ...(superAdmin ? [{ id: "departments", label: "Departments" }] : []),
    { id: "audit", label: "Audit log" },
    ...(superAdmin ? [{ id: "sources", label: "Catalogue sources" }, { id: "system", label: "System" }] : []),
  ];
  const adminTab = tabs.some((tab) => tab.id === requestedTab) ? requestedTab : "people";

  return (
    <section className="admin-shell">
      <header className="admin-page-header">
        <div>
          <p className="admin-eyebrow">Administration</p>
          <h1>Admin</h1>
          <p className="admin-lead">Access, audit and system settings.</p>
        </div>
      </header>

      <nav className="admin-tabs" aria-label="Admin sections">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            className={adminTab === t.id ? "is-on" : undefined}
            aria-current={adminTab === t.id ? "page" : undefined}
            onClick={() => navigate(t.id === "people" ? "/admin" : `/admin/${t.id}`)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {adminTab === "people" && (
        <div className="admin-panel">
          <div className="admin-panel-head">
            <h2>
              People <span className="admin-count-pill">{filteredUsers.length}</span>
            </h2>
            <div className="admin-panel-tools">
              <label className="admin-search">
                <input
                  type="search"
                  value={peopleQuery}
                  onChange={(e) => setPeopleQuery(e.target.value)}
                  placeholder="Search people"
                  aria-label="Search people"
                />
                <Search size={15} strokeWidth={2} aria-hidden="true" />
              </label>
              <select
                className="admin-select"
                value={roleFilter}
                onChange={(e) => setRoleFilter(e.target.value)}
                aria-label="Filter by role"
              >
                <option value="">All roles</option>
                <option value="super_admin">super admin</option>
                <option value="department_admin">department admin</option>
                <option value="department_user">department user</option>
              </select>
            </div>
          </div>

          {requests.length > 0 && (
            <div className="admin-subblock">
              <h3>Pending requests <span className="admin-count-pill">{requests.length}</span></h3>
              <div className="admin-table-wrap">
                <table className="admin-table">
                  <thead>
                    <tr>
                      <th>Applicant</th>
                      <th>Department</th>
                      <th>Requested role</th>
                      <th>Clearance</th>
                      <th>Submitted</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {requests.map((request) => (
                      <tr key={request.id}>
                        <td>
                          <strong>{request.full_name}</strong>
                          <br />
                          <small>{request.email}</small>
                        </td>
                        <td>{request.requested_department}</td>
                        <td>{title(request.requested_role)}</td>
                        <td>
                          {request.requested_role === "department_admin" ? (
                            "operator"
                          ) : (
                            <select
                              value={clearances[request.id] ?? "viewer"}
                              onChange={(event) =>
                                setClearances((current) => ({
                                  ...current,
                                  [request.id]: event.target.value,
                                }))
                              }
                            >
                              <option value="viewer">viewer</option>
                              <option value="operator">operator</option>
                            </select>
                          )}
                        </td>
                        <td>{new Date(request.created_at).toLocaleString()}</td>
                        <td className="row-actions">
                          <button className="link-btn" disabled={busy} onClick={() => approve(request)}>
                            Approve
                          </button>
                          <button className="link-btn danger" disabled={busy} onClick={() => reject(request)}>
                            Reject
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Person</th>
                  <th>Role</th>
                  <th>Home</th>
                  <th>Access</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {filteredUsers.map((account) => (
                  <tr key={account.id} className={account.status === "active" ? "" : "is-idle"}>
                    <td>
                      <div className="admin-person-cell">
                        <span className="admin-avatar">{userInitials(account)}</span>
                        <span>
                          <strong>{account.full_name}</strong>
                          <small>{account.email}</small>
                        </span>
                      </div>
                    </td>
                    <td>{title(account.role)}</td>
                    <td>{account.home_department || "—"}</td>
                    <td className="admin-access-cell">{accessLabel(account)}</td>
                    <td>
                      <span
                        className={
                          account.status === "active"
                            ? "watchlist-status-pill is-active"
                            : "watchlist-status-pill is-idle"
                        }
                      >
                        {account.status === "active" ? "active" : account.status}
                      </span>
                    </td>
                    <td className="admin-td-actions">
                      <button
                        type="button"
                        className="registry-icon-btn"
                        title={account.status === "active" ? "Disable" : "Enable"}
                        disabled={busy || account.id === user.id}
                        onClick={() =>
                          perform(
                            () =>
                              api(`/admin/users/${account.id}/status`, {
                                method: "PUT",
                                headers: { "Content-Type": "application/json" },
                                body: JSON.stringify({
                                  status: account.status === "active" ? "disabled" : "active",
                                }),
                              }),
                            `${account.full_name} is now ${account.status === "active" ? "disabled" : "active"}`,
                          )
                        }
                      >
                        <KeyRound size={15} strokeWidth={2} />
                      </button>
                    </td>
                  </tr>
                ))}
                {filteredUsers.length === 0 && (
                  <tr>
                    <td colSpan={6} className="hint">
                      No people match the current filter.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {/* Grant management kept available under expanded details for operators who need it */}
          <details className="admin-grants-details">
            <summary>Manage department grants</summary>
            <div ref={userListRef} className="admin-user-list">
              {users.map((account) => {
                const available = departments.filter(
                  (department) => !account.grants.some((grant) => grant.department === department.name),
                );
                const draft = {
                  department: available[0]?.name ?? "",
                  clearance: "viewer",
                  ...newGrants[account.id],
                };
                return (
                  <article
                    className={`admin-user-card${account.status === "active" ? "" : " admin-user-card-off"}`}
                    key={account.id}
                  >
                    <header className="admin-user-title">
                      <div className="admin-user-ident">
                        <strong>{account.full_name}</strong>
                        <span className="admin-user-role">{title(account.role)}</span>
                        <small>{account.email}</small>
                      </div>
                    </header>
                    <div className="grant-block">
                      <h4 className="grant-heading">Department access</h4>
                      {account.grants.length === 0 ? (
                        <p className="hint grant-empty">
                          {account.role === "super_admin"
                            ? "Global — every department, by role."
                            : "None yet."}
                        </p>
                      ) : (
                        <div className="grant-list">
                          {account.grants.map((grant) => (
                            <div className="grant-row" key={grant.department}>
                              <span className="grant-dept">
                                {grant.department}
                                {grant.is_home && <span className="grant-home">home</span>}
                              </span>
                              <select
                                aria-label={`${grant.department} clearance`}
                                value={grant.clearance}
                                disabled={busy}
                                onChange={(event) => setGrant(account, grant.department, event.target.value)}
                              >
                                <option value="viewer">viewer</option>
                                <option value="operator">operator</option>
                              </select>
                              {superAdmin && !grant.is_home ? (
                                <button
                                  className="link-btn danger"
                                  disabled={busy}
                                  onClick={() => revokeGrant(account, grant.department)}
                                >
                                  Revoke
                                </button>
                              ) : (
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
                              <option key={department.name} value={department.name}>
                                {department.name}
                              </option>
                            ))}
                          </select>
                          <select
                            aria-label="Clearance to grant"
                            value={draft.clearance}
                            onChange={(event) => setGrantDraft(account.id, "clearance", event.target.value)}
                          >
                            <option value="viewer">viewer</option>
                            <option value="operator">operator</option>
                          </select>
                          <button className="secondary" disabled={busy} onClick={() => addGrant(account, draft)}>
                            Add grant
                          </button>
                        </div>
                      </div>
                    )}
                  </article>
                );
              })}
            </div>
          </details>
        </div>
      )}

      {adminTab === "departments" && superAdmin && (
        <div className="admin-panel">
          <div className="admin-panel-head">
            <h2>
              Departments <span className="admin-count-pill">{departments.length}</span>
            </h2>
            <form className="admin-dept-form" onSubmit={createDepartment}>
              <input
                required
                minLength={2}
                placeholder="New department"
                value={newDepartment}
                onChange={(event) => setNewDepartment(event.target.value)}
                aria-label="New department name"
              />
              <button className="primary admin-create-btn" disabled={busy} type="submit">
                + Create
              </button>
            </form>
          </div>
          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Department</th>
                  <th>Admins</th>
                  <th>Members</th>
                  <th>Cameras</th>
                </tr>
              </thead>
              <tbody>
                {departments.map((department) => {
                  const members = users.filter((account) => account.home_department === department.name);
                  const admins = members.filter((account) => account.role === "department_admin");
                  const departmentUsers = members.filter((account) => account.role === "department_user");
                  return (
                    <tr key={department.name}>
                      <td>
                        <strong>{department.name}</strong>
                      </td>
                      <td className="mono">{admins.length}</td>
                      <td className="mono">{departmentUsers.length}</td>
                      <td className="mono">{camerasInDept(department.name)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {adminTab === "audit" && (
        <div className="admin-panel">
          <div className="admin-panel-head">
            <h2>
              Audit log <span className="admin-count-pill">{audit.total}</span>
            </h2>
            <div className="admin-panel-tools">
              <label className="admin-search">
                <input
                  type="search"
                  value={auditQuery}
                  onChange={(e) => setAuditQuery(e.target.value)}
                  placeholder="Filter this page"
                  aria-label="Filter audit"
                />
                <Search size={15} strokeWidth={2} aria-hidden="true" />
              </label>
              <select
                className="admin-select"
                value={auditResultFilter}
                onChange={(e) => setAuditResultFilter(e.target.value)}
                aria-label="Filter by result"
              >
                <option value="">All results</option>
                <option value="success">success</option>
                <option value="failure">failure</option>
                <option value="denied">denied</option>
                <option value="partial">partial</option>
              </select>
              {superAdmin && (
                <>
                  {/* The full cross-department history as a digest-verifiable
                      download; super admin only, enforced by the API. */}
                  <a className="secondary admin-tool-btn" href={`${API}/admin/audit-events/export`}>
                    <Download size={15} strokeWidth={2} aria-hidden="true" />
                    Export
                  </a>
                  <button type="button" className="secondary admin-tool-btn" onClick={archiveAudit} disabled={archiving}>
                    <Archive size={15} strokeWidth={2} aria-hidden="true" />
                    {archiving ? "Archiving…" : "Archive"}
                  </button>
                </>
              )}
            </div>
          </div>
          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Actor</th>
                  <th>Action</th>
                  <th>Department</th>
                  <th>Result</th>
                </tr>
              </thead>
              <tbody>
                {filteredAudit.map((event) => (
                  <tr key={event.id}>
                    <td className="mono admin-td-time">
                      {new Date(event.occurred_at).toLocaleString(undefined, {
                        month: "short",
                        day: "numeric",
                        hour: "2-digit",
                        minute: "2-digit",
                        second: "2-digit",
                        hour12: false,
                      })}
                    </td>
                    <td>{event.actor_email ?? "system"}</td>
                    <td className="admin-td-action">
                      <strong>{event.action}</strong>
                      {event.resource && <span>{event.resource}</span>}
                    </td>
                    <td>{event.department ?? "—"}</td>
                    <td>
                      <span
                        className={
                          event.result === "success"
                            ? "watchlist-status-pill is-active"
                            : "watchlist-status-pill is-idle"
                        }
                      >
                        {event.result}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {filteredAudit.length === 0 && <p className="hint">No audit events on this page.</p>}
          {audit.total > AUDIT_PAGE_SIZE && (
            <div className="audit-pager">
              <button
                className="secondary"
                disabled={auditOffset === 0}
                onClick={() => setAuditOffset((current) => Math.max(0, current - AUDIT_PAGE_SIZE))}
              >
                Newer
              </button>
              <span className="hint">
                {auditOffset + 1}–{Math.min(auditOffset + AUDIT_PAGE_SIZE, audit.total)} of {audit.total}
              </span>
              <button
                className="secondary"
                disabled={auditOffset + AUDIT_PAGE_SIZE >= audit.total}
                onClick={() => setAuditOffset((current) => current + AUDIT_PAGE_SIZE)}
              >
                Older
              </button>
            </div>
          )}
        </div>
      )}

      {adminTab === "sources" && superAdmin && (
        <div className="admin-panel">
          <div className="admin-panel-head">
            <h2>Catalogue sources</h2>
            <button
              type="button"
              className="primary"
              onClick={() => setShowRegisterSource((v) => !v)}
            >
              + Register source
            </button>
          </div>
          {sources.length === 0 ? (
            <div className="admin-empty-state">
              <Database size={28} strokeWidth={1.5} />
              <strong>No additional sources</strong>
              <p>The official catalogue is configured separately.</p>
            </div>
          ) : (
            <div className="admin-table-wrap">
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Adapter</th>
                    <th>Host</th>
                    <th>Status</th>
                    <th>Last synced</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {sources.map((source) => (
                    <tr key={source.id}>
                      <td>
                        <strong>{source.name}</strong>
                      </td>
                      <td>{source.adapter}</td>
                      <td>{maskUrl(source.base_url)}</td>
                      <td>
                        <span
                          className={
                            source.active
                              ? "watchlist-status-pill is-active"
                              : "watchlist-status-pill is-idle"
                          }
                        >
                          {source.active ? "active" : "deactivated"}
                        </span>
                      </td>
                      <td>
                        {source.last_synced_at
                          ? new Date(source.last_synced_at).toLocaleString()
                          : "never"}
                      </td>
                      <td className="row-actions">
                        <button
                          className="link-btn"
                          disabled={busy || !source.active}
                          onClick={() => syncSource(source)}
                        >
                          Sync now
                        </button>
                        <button className="link-btn" disabled={busy} onClick={() => toggleSourceActive(source)}>
                          {source.active ? "Deactivate" : "Activate"}
                        </button>
                        <button className="link-btn danger" disabled={busy} onClick={() => deleteSource(source)}>
                          Delete
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {showRegisterSource && (
            <form className="admin-source-form" onSubmit={createSource}>
              <h4 className="grant-heading">Register a source</h4>
              <div className="admin-source-form-grid">
                <input
                  required
                  placeholder="Name (e.g. Live Corp)"
                  value={newSource.name}
                  onChange={(event) => setNewSource((c) => ({ ...c, name: event.target.value }))}
                />
                <select
                  value={newSource.adapter}
                  onChange={(event) => setNewSource((c) => ({ ...c, adapter: event.target.value }))}
                >
                  <option value="sentinel_default">sentinel_default</option>
                </select>
                <input
                  required
                  type="url"
                  placeholder="Catalogue base URL"
                  value={newSource.base_url}
                  onChange={(event) => setNewSource((c) => ({ ...c, base_url: event.target.value }))}
                />
                <input
                  placeholder="Browser base URL (optional)"
                  value={newSource.browser_base_url}
                  onChange={(event) =>
                    setNewSource((c) => ({ ...c, browser_base_url: event.target.value }))
                  }
                />
                <input
                  placeholder="Auth header name (optional)"
                  value={newSource.auth_header_name}
                  onChange={(event) =>
                    setNewSource((c) => ({ ...c, auth_header_name: event.target.value }))
                  }
                />
                <input
                  type="password"
                  placeholder="Auth secret (optional)"
                  value={newSource.auth_secret}
                  onChange={(event) => setNewSource((c) => ({ ...c, auth_secret: event.target.value }))}
                />
              </div>
              <label className="admin-source-checkbox">
                <input
                  type="checkbox"
                  checked={newSource.allow_private_host}
                  onChange={(event) =>
                    setNewSource((c) => ({ ...c, allow_private_host: event.target.checked }))
                  }
                />
                Allow a private/loopback host (local testing only)
              </label>
              <button className="primary" disabled={busy}>
                Register source
              </button>
            </form>
          )}
        </div>
      )}

      {adminTab === "system" && superAdmin && (
        <div className="admin-panel">
          <div className="admin-panel-head">
            <h2>System</h2>
          </div>
          <div className="admin-system-cards">
            <div className="admin-system-card">
              <div className="admin-system-card-icon">
                <Film size={18} strokeWidth={1.75} />
              </div>
              <div className="admin-system-card-body">
                <strong>Government mode</strong>
                <p>Replay recorded government footage as live camera streams.</p>
                {governmentMode?.enabled && (
                  <small>
                    {governmentMode.camera_ids?.length ?? 0} cameras on the relay
                  </small>
                )}
              </div>
              <div className="admin-system-card-toggle">
                <span className={governmentMode?.enabled ? "on-label" : "off-label"}>
                  {governmentMode?.enabled ? "On" : "Off"}
                </span>
                <label className="switch">
                  <input
                    type="checkbox"
                    checked={!!governmentMode?.enabled}
                    disabled={governmentBusy || governmentMode === null}
                    onChange={(event) => toggleGovernmentMode(event.target.checked)}
                  />
                </label>
              </div>
            </div>
            <div className="admin-system-card">
              <div className="admin-system-card-icon is-muted">
                <Film size={18} strokeWidth={1.75} />
              </div>
              <div className="admin-system-card-body">
                <strong>Demo mode</strong>
                <p>Rehearsal cameras with synthetic footage and a sample watchlist plate.</p>
                {demoMode?.enabled && (
                  <small>
                    Active — {demoMode.camera_count} camera(s), plate {demoMode.plate}
                  </small>
                )}
              </div>
              <div className="admin-system-card-toggle">
                <span className={demoMode?.enabled ? "on-label" : "off-label"}>
                  {demoMode?.enabled ? "On" : "Off"}
                </span>
                <label className="switch">
                  <input
                    type="checkbox"
                    checked={!!demoMode?.enabled}
                    disabled={demoBusy || demoMode === null}
                    onChange={(event) => toggleDemoMode(event.target.checked)}
                  />
                </label>
              </div>
            </div>
          </div>
          <p className="hint admin-system-note">
            Only one mode can be on at a time. Recorded footage is not a live deployment.
          </p>
        </div>
      )}
      {confirmDialog}
    </section>
  );
}
