import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ListX, Pencil, Plus, Search, Trash2, Upload } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { Page, PageHeader, Toolbar, useConfirm } from "../../components/Page.jsx";
import { Badge, Button, Checkbox, Dialog, EmptyState, Field, IconButton, Input, PlateChip, Select, Skeleton, Textarea } from "../../components/ui.jsx";
import { api } from "../../lib/api/client.js";
import { fmtDate, humanize } from "../../lib/format.js";
import { usePageTitle } from "../../lib/hooks.js";
import { isSuperAdmin } from "../../lib/permissions.js";
import { useAuth } from "../auth/AuthProvider.jsx";
import { toast } from "../notifications/notificationStore.js";

const SEVERITIES = ["low", "medium", "high"];
const SEVERITY_TONE = { high: "critical", medium: "pending", low: undefined };
const EMPTY = { raw_value: "", reason_code: "", severity: "medium", notes: "", source: "", active: true };

function EntryDialog({ open, entry, onClose, onSaved }) {
  const [form, setForm] = useState(EMPTY);
  const [saving, setSaving] = useState(false);
  const editing = Boolean(entry);

  useEffect(() => {
    if (!open) return;
    setForm(
      entry
        ? {
            raw_value: entry.raw_value,
            reason_code: entry.reason_code ?? "",
            severity: entry.severity,
            notes: entry.notes ?? "",
            source: entry.source ?? "",
            active: entry.active,
          }
        : EMPTY,
    );
  }, [entry, open]);

  const set = (field, value) => setForm((current) => ({ ...current, [field]: value }));

  async function submit(event) {
    event.preventDefault();
    setSaving(true);
    try {
      if (editing) {
        await api(`/watchlist/${entry.id}`, {
          method: "PUT",
          json: {
            reason_code: form.reason_code || null,
            severity: form.severity,
            notes: form.notes || null,
            source: form.source || null,
            active: form.active,
          },
        });
        toast("Watchlist entry saved", { tone: "live" });
      } else {
        await api("/watchlist", {
          method: "POST",
          json: {
            raw_value: form.raw_value,
            reason_code: form.reason_code || undefined,
            severity: form.severity,
            notes: form.notes || undefined,
            source: form.source || undefined,
            active: form.active,
          },
        });
        toast(`${form.raw_value.toUpperCase()} added to the watchlist`, { tone: "live" });
      }
      await onSaved();
      onClose();
    } catch (error) {
      toast("Couldn't save the entry", { tone: "critical", detail: error.message });
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      busy={saving}
      title={editing ? "Edit watchlist entry" : "Add to watchlist"}
      description={editing ? "The plate itself can't be changed. Remove the entry and add it again instead." : "New sightings of this plate raise an alert when read with confidence."}
    >
      <form id="watchlist-form" onSubmit={submit} style={{ display: "grid", gap: 16 }}>
        <Field label="Plate" htmlFor="wl-plate">
          <Input id="wl-plate" required={!editing} disabled={editing} value={form.raw_value} onChange={(e) => set("raw_value", e.target.value)} placeholder="GJ01AB1234" autoCapitalize="characters" />
        </Field>
        <div className="ui-grid-2">
          <Field label="Reason" htmlFor="wl-reason">
            <Input id="wl-reason" value={form.reason_code} onChange={(e) => set("reason_code", e.target.value)} placeholder="stolen_vehicle" />
          </Field>
          <Field label="Severity" htmlFor="wl-severity">
            <Select id="wl-severity" value={form.severity} onChange={(e) => set("severity", e.target.value)}>
              {SEVERITIES.map((severity) => (
                <option key={severity} value={severity}>
                  {severity}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <Field label="Source" htmlFor="wl-source">
          <Input id="wl-source" value={form.source} onChange={(e) => set("source", e.target.value)} placeholder="Where this entry came from" />
        </Field>
        <Field label="Notes" htmlFor="wl-notes">
          <Textarea id="wl-notes" rows={3} value={form.notes} onChange={(e) => set("notes", e.target.value)} />
        </Field>
        <Checkbox label="Active — match new sightings" checked={form.active} onChange={(e) => set("active", e.target.checked)} />
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <Button variant="ghost" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" loading={saving}>
            {editing ? "Save" : "Add entry"}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

export default function WatchlistView() {
  usePageTitle("Watchlist");
  const { user } = useAuth();
  const canManage = isSuperAdmin(user);
  const queryClient = useQueryClient();
  const [activeOnly, setActiveOnly] = useState(false);
  const [search, setSearch] = useState("");
  const [dialog, setDialog] = useState({ open: false, entry: null });
  const [confirm, confirmDialog] = useConfirm();
  const fileRef = useRef(null);

  const entries = useQuery({
    queryKey: ["watchlist", activeOnly],
    queryFn: () => api(`/watchlist${activeOnly ? "?active=true" : ""}`),
  });

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["watchlist"] });

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase().replace(/\s+/g, "");
    if (!needle) return entries.data ?? [];
    return (entries.data ?? []).filter((entry) =>
      [entry.normalised_value, entry.raw_value, entry.reason_code, entry.source].filter(Boolean).some((value) => String(value).toLowerCase().replace(/\s+/g, "").includes(needle)),
    );
  }, [entries.data, search]);

  async function remove(entry) {
    const ok = await confirm({
      title: `Remove ${entry.raw_value}?`,
      body: "New sightings of this plate will no longer raise alerts. Existing alerts are kept.",
      confirmLabel: "Remove",
      danger: true,
    });
    if (!ok) return;
    try {
      await api(`/watchlist/${entry.id}`, { method: "DELETE" });
      toast(`${entry.raw_value} removed`, { tone: "live" });
      refresh();
    } catch (error) {
      toast("Couldn't remove the entry", { tone: "critical", detail: error.message });
    }
  }

  async function bulkImport(event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    const body = new FormData();
    body.append("file", file);
    try {
      const result = await api("/watchlist/bulk", { method: "POST", body });
      toast(`Imported ${result.added} of ${result.total_rows}`, {
        tone: result.failed ? "critical" : "live",
        detail: result.failed ? `${result.failed} row(s) failed validation.` : undefined,
      });
      refresh();
    } catch (error) {
      toast("Import failed", { tone: "critical", detail: error.message });
    }
  }

  return (
    <Page>
      <PageHeader
        overline="Monitoring"
        title="Watchlist"
        description="Plates that raise an alert when a camera confirms them."
        actions={
          canManage && (
            <>
              <input ref={fileRef} type="file" accept=".csv" hidden onChange={bulkImport} />
              <Button icon={<Upload />} onClick={() => fileRef.current?.click()}>
                Import CSV
              </Button>
              <Button variant="primary" icon={<Plus />} onClick={() => setDialog({ open: true, entry: null })}>
                Add plate
              </Button>
            </>
          )
        }
      />

      <Toolbar label="Watchlist filters">
        <div className="ui-search">
          <Search aria-hidden="true" />
          <Input type="search" placeholder="Search plate, reason or source" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search watchlist" />
        </div>
        <Checkbox label="Active only" checked={activeOnly} onChange={(e) => setActiveOnly(e.target.checked)} />
      </Toolbar>

      {entries.isPending ? (
        <Skeleton height={260} />
      ) : rows.length === 0 ? (
        <div className="ui-card">
          <EmptyState icon={<ListX />} title={search ? "No entries match" : "The watchlist is empty"}>
            {canManage ? "Add a plate, or import a CSV of plates." : "A super admin manages watchlist entries."}
          </EmptyState>
        </div>
      ) : (
        <div className="ui-table-wrap">
          <table className="ui-table">
            <thead>
              <tr>
                <th>Plate</th>
                <th>Reason</th>
                <th>Severity</th>
                <th>Source</th>
                <th>Status</th>
                <th>Added</th>
                <th>
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((entry) => (
                <tr key={entry.id}>
                  <td>
                    <Link to={`/journeys/${encodeURIComponent(entry.normalised_value)}`} title="View journey">
                      <PlateChip plate={entry.normalised_value} />
                    </Link>
                  </td>
                  <td>
                    {entry.reason_code ? humanize(entry.reason_code) : <span className="faint">—</span>}
                    {entry.notes && <span className="ui-table__secondary">{entry.notes}</span>}
                  </td>
                  <td>
                    <Badge tone={SEVERITY_TONE[entry.severity]}>{entry.severity}</Badge>
                  </td>
                  <td>{entry.source ?? <span className="faint">—</span>}</td>
                  <td>
                    <Badge tone={entry.active ? "live" : undefined}>{entry.active ? "active" : "inactive"}</Badge>
                  </td>
                  <td className="data">{fmtDate(entry.created_at)}</td>
                  <td>
                    {canManage && (
                      <div className="ui-table__actions">
                        <IconButton label="Edit" size="sm" onClick={() => setDialog({ open: true, entry })}>
                          <Pencil />
                        </IconButton>
                        <IconButton label="Remove" size="sm" onClick={() => remove(entry)}>
                          <Trash2 />
                        </IconButton>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {canManage && <EntryDialog open={dialog.open} entry={dialog.entry} onClose={() => setDialog({ open: false, entry: null })} onSaved={refresh} />}
      {confirmDialog}
    </Page>
  );
}
