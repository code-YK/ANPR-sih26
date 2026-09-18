import { useQuery } from "@tanstack/react-query";
import { Check, Plus, Search, Settings2, Users, X } from "lucide-react";
import { useMemo, useState } from "react";

import { Badge, Button, Dialog, EmptyState, Field, IconButton, Input, Select, Skeleton, Textarea, Tooltip } from "../../components/ui.jsx";
import { api } from "../../lib/api/client.js";
import { humanize } from "../../lib/format.js";
import { usePageTitle } from "../../lib/hooks.js";
import { isSuperAdmin } from "../../lib/permissions.js";
import { useDepartments } from "../../lib/queries.js";
import { useAuth } from "../auth/AuthProvider.jsx";
import { Person, SectionBar, useAdminAction } from "./shared.jsx";
import styles from "./Admin.module.css";

// ---------------------------------------------------------------------------
// Pending access requests
// ---------------------------------------------------------------------------
function Requests() {
  const [run, busy] = useAdminAction();
  const [clearances, setClearances] = useState({});
  const [rejecting, setRejecting] = useState(null);
  const [reason, setReason] = useState("");
  const requests = useQuery({
    queryKey: ["admin", "requests"],
    queryFn: () => api("/admin/registration-requests?request_status=pending"),
    refetchInterval: 30_000,
  });

  const rows = requests.data ?? [];
  if (requests.isPending || rows.length === 0) return null;

  return (
    <section className={`ui-card ${styles.requests}`}>
      <SectionBar title="Access requests" count={rows.length} />
      <ul className={styles.requestList}>
        {rows.map((request) => {
          const adminRequest = request.requested_role === "department_admin";
          const clearance = adminRequest ? "operator" : clearances[request.id] ?? "viewer";
          return (
            <li key={request.id} className={styles.requestRow}>
              <Person name={request.full_name} email={request.email} />
              <span className={styles.muted}>
                {request.requested_department} · {humanize(request.requested_role)}
              </span>
              {adminRequest ? (
                <Badge>operator</Badge>
              ) : (
                <Select size="sm" value={clearance} onChange={(e) => setClearances((current) => ({ ...current, [request.id]: e.target.value }))} aria-label="Clearance">
                  <option value="viewer">viewer</option>
                  <option value="operator">operator</option>
                </Select>
              )}
              <div className={styles.rowActions}>
                <Button size="sm" variant="primary" icon={<Check />} disabled={busy} onClick={() => run(() => api(`/admin/registration-requests/${request.id}/approve`, { method: "POST", json: { clearance } }), `Approved ${request.full_name}`)}>
                  Approve
                </Button>
                <IconButton label="Reject" size="sm" disabled={busy} onClick={() => setRejecting(request)}>
                  <X />
                </IconButton>
              </div>
            </li>
          );
        })}
      </ul>
      <Dialog
        open={Boolean(rejecting)}
        onClose={() => setRejecting(null)}
        title={rejecting ? `Reject ${rejecting.full_name}?` : ""}
        footer={
          <>
            <Button variant="ghost" onClick={() => setRejecting(null)}>
              Cancel
            </Button>
            <Button
              variant="danger-solid"
              disabled={!reason.trim() || busy}
              onClick={async () => {
                if (await run(() => api(`/admin/registration-requests/${rejecting.id}/reject`, { method: "POST", json: { reason } }), `Rejected ${rejecting.full_name}`)) {
                  setRejecting(null);
                  setReason("");
                }
              }}
            >
              Reject
            </Button>
          </>
        }
      >
        <Field label="Reason" hint="Recorded in the audit log.">
          <Textarea rows={3} value={reason} onChange={(e) => setReason(e.target.value)} autoFocus />
        </Field>
      </Dialog>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Manage one person's access
// ---------------------------------------------------------------------------
function ManageDialog({ account, onClose }) {
  const { user } = useAuth();
  const superAdmin = isSuperAdmin(user);
  const departments = useDepartments();
  const [run, busy] = useAdminAction();
  const [draft, setDraft] = useState({ department: "", clearance: "viewer" });

  if (!account) return <Dialog open={false} onClose={onClose} />;
  const available = (departments.data ?? []).filter((department) => !account.grants.some((grant) => grant.department === department.name));
  const addDepartment = draft.department || available[0]?.name || "";
  const self = account.id === user.id;
  const grantPath = (department) => `/admin/users/${account.id}/grants/${encodeURIComponent(department)}`;

  return (
    <Dialog
      open
      onClose={onClose}
      title={account.full_name}
      description={`${account.email} · ${humanize(account.role)}`}
      footer={
        <>
          <Tooltip content={self ? "You can't change your own status" : null}>
            <span style={{ marginRight: "auto" }}>
              <Button
                variant={account.status === "active" ? "danger" : "secondary"}
                disabled={busy || self}
                onClick={() => run(() => api(`/admin/users/${account.id}/status`, { method: "PUT", json: { status: account.status === "active" ? "disabled" : "active" } }), `${account.full_name} ${account.status === "active" ? "disabled" : "enabled"}`)}
              >
                {account.status === "active" ? "Disable account" : "Enable account"}
              </Button>
            </span>
          </Tooltip>
          <Button variant="primary" onClick={onClose}>
            Done
          </Button>
        </>
      }
    >
      {account.role === "super_admin" ? (
        <p className={styles.muted}>Super admins can access every department.</p>
      ) : (
        <>
          <div className={styles.grantTable} role="table" aria-label="Department access">
            <div className={styles.grantHead} role="row">
              <span role="columnheader">Department</span>
              <span role="columnheader">Clearance</span>
              <span role="columnheader" className="visually-hidden">
                Actions
              </span>
            </div>
            {account.grants.length === 0 && <p className={styles.muted}>No department access yet.</p>}
            {account.grants.map((grant) => (
              <div key={grant.department} className={styles.grantRow} role="row">
                <span className={styles.grantName} role="cell">
                  {grant.department}
                  {grant.is_home && <Badge outline>home</Badge>}
                </span>
                <span role="cell">
                  <Select size="sm" value={grant.clearance} disabled={busy} aria-label={`${grant.department} clearance`} onChange={(e) => run(() => api(grantPath(grant.department), { method: "PUT", json: { clearance: e.target.value } }), `Updated ${grant.department}`)}>
                    <option value="viewer">viewer</option>
                    <option value="operator">operator</option>
                  </Select>
                </span>
                <span role="cell" className={styles.grantAction}>
                  {superAdmin && !grant.is_home && (
                    <IconButton label={`Remove ${grant.department}`} size="sm" disabled={busy} onClick={() => run(() => api(grantPath(grant.department), { method: "DELETE" }), `Removed ${grant.department}`)}>
                      <X />
                    </IconButton>
                  )}
                </span>
              </div>
            ))}
          </div>
          {superAdmin && available.length > 0 && (
            <div className={styles.grantRow} data-add>
              <Select size="sm" value={addDepartment} onChange={(e) => setDraft((current) => ({ ...current, department: e.target.value }))} aria-label="Department to add">
                {available.map((department) => (
                  <option key={department.name} value={department.name}>
                    {department.name}
                  </option>
                ))}
              </Select>
              <Select size="sm" value={draft.clearance} onChange={(e) => setDraft((current) => ({ ...current, clearance: e.target.value }))} aria-label="Clearance to add">
                <option value="viewer">viewer</option>
                <option value="operator">operator</option>
              </Select>
              <Button size="sm" icon={<Plus />} disabled={busy || !addDepartment} onClick={() => run(() => api(grantPath(addDepartment), { method: "PUT", json: { clearance: draft.clearance } }), `Added ${addDepartment}`).then(() => setDraft({ department: "", clearance: "viewer" }))}>
                Add
              </Button>
            </div>
          )}
        </>
      )}
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// People
// ---------------------------------------------------------------------------
function AccessChips({ account }) {
  if (account.role === "super_admin") return <span className={styles.muted}>All departments</span>;
  if (account.grants.length === 0) return <span className={styles.faint}>None</span>;
  const shown = account.grants.slice(0, 2);
  return (
    <span className={styles.chips}>
      {shown.map((grant) => (
        <span key={grant.department} className={styles.chip}>
          {grant.department}
          <span className={styles.chipLevel}>{grant.clearance}</span>
        </span>
      ))}
      {account.grants.length > shown.length && <span className={styles.faint}>+{account.grants.length - shown.length}</span>}
    </span>
  );
}

export default function PeopleSection() {
  usePageTitle("Admin · People");
  const users = useQuery({ queryKey: ["admin", "users"], queryFn: () => api("/admin/users") });
  const [query, setQuery] = useState("");
  const [role, setRole] = useState("");
  const [managingId, setManagingId] = useState(null);

  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (users.data ?? []).filter((account) => {
      if (role && account.role !== role) return false;
      if (!needle) return true;
      return [account.full_name, account.email, account.home_department].filter(Boolean).some((value) => value.toLowerCase().includes(needle));
    });
  }, [users.data, query, role]);

  const managing = (users.data ?? []).find((account) => account.id === managingId) ?? null;

  return (
    <div className={styles.stack}>
      <Requests />

      <section className={styles.block}>
        <SectionBar title="People" count={users.data?.length}>
          <div className="ui-search">
            <Search aria-hidden="true" />
            <Input size="sm" type="search" placeholder="Search people" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search people" />
          </div>
          <Select size="sm" value={role} onChange={(e) => setRole(e.target.value)} aria-label="Role" className={styles.filterSelect}>
            <option value="">All roles</option>
            <option value="super_admin">Super admin</option>
            <option value="department_admin">Department admin</option>
            <option value="department_user">Department user</option>
          </Select>
        </SectionBar>

        {users.isPending ? (
          <Skeleton height={240} />
        ) : rows.length === 0 ? (
          <div className="ui-card">
            <EmptyState compact icon={<Users />} title="No one matches" />
          </div>
        ) : (
          <div className="ui-table-wrap">
            <table className="ui-table">
              <colgroup>
                <col style={{ width: "30%" }} />
                <col style={{ width: "16%" }} />
                <col style={{ width: "14%" }} />
                <col />
                <col style={{ width: "10%" }} />
                <col style={{ width: 64 }} />
              </colgroup>
              <thead>
                <tr>
                  <th>Person</th>
                  <th>Role</th>
                  <th>Home</th>
                  <th>Access</th>
                  <th>Status</th>
                  <th>
                    <span className="visually-hidden">Manage</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((account) => (
                  <tr key={account.id} className={account.status !== "active" ? styles.inactive : undefined}>
                    <td>
                      <Person name={account.full_name} email={account.email} />
                    </td>
                    <td className={styles.muted}>{humanize(account.role)}</td>
                    <td className={styles.muted}>{account.home_department ?? "—"}</td>
                    <td>
                      <AccessChips account={account} />
                    </td>
                    <td>
                      <Badge tone={account.status === "active" ? "live" : undefined}>{account.status}</Badge>
                    </td>
                    <td>
                      <div className="ui-table__actions">
                        <IconButton label={`Manage ${account.full_name}`} size="sm" onClick={() => setManagingId(account.id)}>
                          <Settings2 />
                        </IconButton>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <ManageDialog account={managing} onClose={() => setManagingId(null)} />
    </div>
  );
}
