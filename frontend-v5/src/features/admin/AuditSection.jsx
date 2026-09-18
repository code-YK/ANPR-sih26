import { useQuery } from "@tanstack/react-query";
import { Archive, ChevronLeft, ChevronRight, Download, Search } from "lucide-react";
import { useMemo, useState } from "react";

import { useConfirm } from "../../components/Page.jsx";
import { Badge, Button, IconButton, Input, Select, Skeleton } from "../../components/ui.jsx";
import { api } from "../../lib/api/client.js";
import { apiUrl } from "../../lib/api/media.js";
import { fmtDateTime } from "../../lib/format.js";
import { usePageTitle } from "../../lib/hooks.js";
import { isSuperAdmin } from "../../lib/permissions.js";
import { useAuth } from "../auth/AuthProvider.jsx";
import { toast } from "../notifications/notificationStore.js";
import { SectionBar } from "./shared.jsx";
import styles from "./Admin.module.css";

const PAGE = 50;

export default function AuditSection() {
  usePageTitle("Admin · Audit log");
  const { user } = useAuth();
  const superAdmin = isSuperAdmin(user);
  const [offset, setOffset] = useState(0);
  const [query, setQuery] = useState("");
  const [result, setResult] = useState("");
  const [archiving, setArchiving] = useState(false);
  const [confirm, confirmDialog] = useConfirm();

  const audit = useQuery({
    queryKey: ["admin", "audit", offset],
    queryFn: () => api(`/admin/audit-events?limit=${PAGE}&offset=${offset}`),
    placeholderData: (previous) => previous,
  });

  const events = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (audit.data?.events ?? []).filter((event) => {
      if (result && event.result !== result) return false;
      if (!needle) return true;
      return [event.action, event.actor_email, event.target_id, event.department].filter(Boolean).some((value) => String(value).toLowerCase().includes(needle));
    });
  }, [audit.data, query, result]);

  async function archive() {
    const ok = await confirm({
      title: "Write an audit archive?",
      body: "A verifiable snapshot of every audit event is written to the retention mount. Existing archives are never overwritten.",
      confirmLabel: "Write archive",
    });
    if (!ok) return;
    setArchiving(true);
    try {
      await api("/admin/audit-events/archive", { method: "POST" });
      toast("Audit archive written", { tone: "live" });
    } catch (error) {
      toast("Archive failed", { tone: "critical", detail: error.message });
    } finally {
      setArchiving(false);
    }
  }

  const total = audit.data?.total ?? 0;

  return (
    <section className={styles.block}>
      <SectionBar title="Audit log" count={total || null}>
        <div className="ui-search">
          <Search aria-hidden="true" />
          <Input size="sm" type="search" placeholder="Filter this page" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Filter audit events" />
        </div>
        <Select size="sm" value={result} onChange={(e) => setResult(e.target.value)} aria-label="Result" className={styles.filterSelect}>
          <option value="">All results</option>
          <option value="success">Success</option>
          <option value="failure">Failure</option>
          <option value="denied">Denied</option>
          <option value="partial">Partial</option>
        </Select>
        {superAdmin && (
          <>
            <a className="ui-btn ui-btn--ghost ui-btn--sm" href={apiUrl("/admin/audit-events/export")}>
              <Download aria-hidden="true" /> Export
            </a>
            <Button size="sm" variant="ghost" icon={<Archive />} loading={archiving} onClick={archive}>
              Archive
            </Button>
          </>
        )}
      </SectionBar>

      {audit.isPending ? (
        <Skeleton height={360} />
      ) : (
        <div className="ui-table-wrap">
          <table className="ui-table">
            <colgroup>
              <col style={{ width: 170 }} />
              <col style={{ width: "22%" }} />
              <col />
              <col style={{ width: "18%" }} />
              <col style={{ width: 96 }} />
            </colgroup>
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
              {events.map((event) => (
                <tr key={event.id}>
                  <td className="data faint">{fmtDateTime(event.occurred_at)}</td>
                  <td className={styles.truncate}>{event.actor_email ?? <span className={styles.faint}>system</span>}</td>
                  <td>
                    <span className="data">{event.action}</span>
                    {event.target_id && <span className="ui-table__secondary data">{event.target_id}</span>}
                  </td>
                  <td className={styles.muted}>{event.department ?? "—"}</td>
                  <td>
                    <Badge tone={event.result === "success" ? undefined : "critical"}>{event.result}</Badge>
                  </td>
                </tr>
              ))}
              {events.length === 0 && (
                <tr>
                  <td colSpan={5} className={styles.faint}>
                    Nothing on this page matches.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {total > PAGE && (
        <div className={styles.pager}>
          <span className="faint tabular">
            {offset + 1}–{Math.min(offset + PAGE, total)} of {total}
          </span>
          <IconButton label="Newer" size="sm" disabled={offset === 0} onClick={() => setOffset((value) => Math.max(0, value - PAGE))}>
            <ChevronLeft />
          </IconButton>
          <IconButton label="Older" size="sm" disabled={offset + PAGE >= total} onClick={() => setOffset((value) => value + PAGE)}>
            <ChevronRight />
          </IconButton>
        </div>
      )}
      {confirmDialog}
    </section>
  );
}
