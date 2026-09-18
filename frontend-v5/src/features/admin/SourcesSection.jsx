import { useQuery, useQueryClient } from "@tanstack/react-query";
import { DatabaseZap, Plus, RefreshCw, Trash2 } from "lucide-react";
import { useState } from "react";

import { useConfirm } from "../../components/Page.jsx";
import { Badge, Button, Checkbox, Dialog, EmptyState, Field, IconButton, Input, Select, Skeleton } from "../../components/ui.jsx";
import { api } from "../../lib/api/client.js";
import { fmtDateTime } from "../../lib/format.js";
import { usePageTitle } from "../../lib/hooks.js";
import { keys } from "../../lib/queries.js";
import { SectionBar, useAdminAction } from "./shared.jsx";
import styles from "./Admin.module.css";

const DRAFT = { name: "", adapter: "sentinel_default", base_url: "", browser_base_url: "", auth_header_name: "", auth_secret: "", allow_private_host: false };

function host(url) {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

function RegisterDialog({ open, onClose }) {
  const [draft, setDraft] = useState(DRAFT);
  const [run, busy] = useAdminAction();
  const set = (field, value) => setDraft((current) => ({ ...current, [field]: value }));

  async function submit(event) {
    event.preventDefault();
    const ok = await run(
      () =>
        api("/catalogue-sources", {
          method: "POST",
          json: {
            name: draft.name.trim(),
            adapter: draft.adapter,
            base_url: draft.base_url.trim(),
            browser_base_url: draft.browser_base_url.trim() || null,
            auth_header_name: draft.auth_header_name.trim() || null,
            auth_secret: draft.auth_secret.trim() || null,
            allow_private_host: draft.allow_private_host,
          },
        }),
      `Registered ${draft.name.trim()}`,
    );
    if (ok) {
      setDraft(DRAFT);
      onClose();
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      busy={busy}
      title="Register a catalogue source"
      description="The URL and secret are stored server-side and never shown again."
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button type="submit" form="source-form" variant="primary" loading={busy} disabled={!draft.name.trim() || !draft.base_url.trim()}>
            Register
          </Button>
        </>
      }
    >
      <form id="source-form" onSubmit={submit} className={styles.form}>
        <div className="ui-grid-2">
          <Field label="Name">
            <Input required value={draft.name} onChange={(e) => set("name", e.target.value)} />
          </Field>
          <Field label="Adapter">
            <Select value={draft.adapter} onChange={(e) => set("adapter", e.target.value)}>
              <option value="sentinel_default">sentinel_default</option>
            </Select>
          </Field>
        </div>
        <Field label="Catalogue URL">
          <Input required type="url" value={draft.base_url} onChange={(e) => set("base_url", e.target.value)} placeholder="https://…" />
        </Field>
        <Field label="Browser base URL" hint="Optional">
          <Input value={draft.browser_base_url} onChange={(e) => set("browser_base_url", e.target.value)} />
        </Field>
        <div className="ui-grid-2">
          <Field label="Auth header" hint="Optional">
            <Input value={draft.auth_header_name} onChange={(e) => set("auth_header_name", e.target.value)} placeholder="X-Api-Key" />
          </Field>
          <Field label="Auth secret" hint="Optional">
            <Input type="password" autoComplete="new-password" value={draft.auth_secret} onChange={(e) => set("auth_secret", e.target.value)} />
          </Field>
        </div>
        <Checkbox label="Allow a private or loopback host (testing only)" checked={draft.allow_private_host} onChange={(e) => set("allow_private_host", e.target.checked)} />
      </form>
    </Dialog>
  );
}

export default function SourcesSection() {
  usePageTitle("Admin · Catalogue sources");
  const queryClient = useQueryClient();
  const [run, busy] = useAdminAction();
  const [registering, setRegistering] = useState(false);
  const [confirm, confirmDialog] = useConfirm();
  const sources = useQuery({ queryKey: ["admin", "sources"], queryFn: () => api("/catalogue-sources") });
  const rows = sources.data ?? [];

  return (
    <section className={styles.block}>
      <SectionBar title="Catalogue sources" count={rows.length || null}>
        <Button size="sm" variant="primary" icon={<Plus />} onClick={() => setRegistering(true)}>
          Register source
        </Button>
      </SectionBar>

      {sources.isPending ? (
        <Skeleton height={160} />
      ) : rows.length === 0 ? (
        <div className="ui-card">
          <EmptyState compact icon={<DatabaseZap />} title="No additional sources">
            The official catalogue is configured separately.
          </EmptyState>
        </div>
      ) : (
        <div className="ui-table-wrap">
          <table className="ui-table">
            <colgroup>
              <col style={{ width: "26%" }} />
              <col style={{ width: "24%" }} />
              <col style={{ width: 110 }} />
              <col />
              <col style={{ width: 230 }} />
            </colgroup>
            <thead>
              <tr>
                <th>Source</th>
                <th>Host</th>
                <th>Status</th>
                <th>Last sync</th>
                <th>
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((source) => (
                <tr key={source.id}>
                  <td className="ui-table__primary">{source.name}</td>
                  <td className="data faint">{host(source.base_url)}</td>
                  <td>
                    <Badge tone={source.active ? "live" : undefined}>{source.active ? "active" : "paused"}</Badge>
                  </td>
                  <td>
                    <span className="data">{source.last_synced_at ? fmtDateTime(source.last_synced_at) : "never"}</span>
                    {source.last_sync_result && (
                      <span className="ui-table__secondary">
                        {source.last_sync_result.inserted} new · {source.last_sync_result.updated} updated
                      </span>
                    )}
                  </td>
                  <td>
                    <div className="ui-table__actions">
                      <Button
                        size="sm"
                        icon={<RefreshCw />}
                        disabled={!source.active || busy}
                        onClick={() =>
                          run(
                            () => api(`/catalogue-sources/${source.id}/sync`, { method: "POST" }),
                            (result) => `${source.name}: ${result.inserted} new, ${result.updated} updated`,
                            [keys.cameras],
                          )
                        }
                      >
                        Sync
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={busy}
                        onClick={() => run(() => api(`/catalogue-sources/${source.id}`, { method: "PUT", json: { active: !source.active } }), `${source.name} ${source.active ? "paused" : "activated"}`)}
                      >
                        {source.active ? "Pause" : "Activate"}
                      </Button>
                      <IconButton
                        label={`Delete ${source.name}`}
                        size="sm"
                        disabled={busy}
                        onClick={async () => {
                          const ok = await confirm({ title: `Delete ${source.name}?`, body: "Only possible when no camera still references it.", confirmLabel: "Delete", danger: true });
                          if (ok) run(() => api(`/catalogue-sources/${source.id}`, { method: "DELETE" }), `Deleted ${source.name}`);
                        }}
                      >
                        <Trash2 />
                      </IconButton>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <RegisterDialog open={registering} onClose={() => { setRegistering(false); queryClient.invalidateQueries({ queryKey: ["admin", "sources"] }); }} />
      {confirmDialog}
    </section>
  );
}
