import { useQueryClient } from "@tanstack/react-query";
import { Clapperboard, FileVideo } from "lucide-react";
import { useState } from "react";

import { Badge, Spinner, Switch, Tooltip } from "../../components/ui.jsx";
import { api } from "../../lib/api/client.js";
import { fmtDateTime } from "../../lib/format.js";
import { usePageTitle } from "../../lib/hooks.js";
import { keys, useModes } from "../../lib/queries.js";
import { toast } from "../notifications/notificationStore.js";
import { SectionBar } from "./shared.jsx";
import styles from "./Admin.module.css";

function SettingRow({ icon, title, description, status, busy, onToggle, detail }) {
  const enabled = Boolean(status?.enabled);
  return (
    <div className={styles.setting} data-on={enabled || undefined}>
      <span className={styles.settingIcon} aria-hidden="true">
        {icon}
      </span>
      <div className={styles.settingText}>
        <span className={styles.settingTitle}>{title}</span>
        <span className={styles.settingDescription}>{description}</span>
        {enabled && detail}
      </div>
      <div className={styles.settingControl}>
        {enabled ? (
          <Tooltip content={`Since ${fmtDateTime(status.activated_at)}`}>
            <span>
              <Badge tone={status.degraded ? "pending" : "live"}>{status.degraded ? "Needs repair" : "On"}</Badge>
            </span>
          </Tooltip>
        ) : (
          <Badge outline>Off</Badge>
        )}
        {busy ? <Spinner /> : <Switch label={`${title} ${enabled ? "on" : "off"}`} checked={enabled} disabled={status == null} onChange={(e) => onToggle(e.target.checked)} />}
      </div>
    </div>
  );
}

export default function SystemSection() {
  usePageTitle("Admin · System");
  const queryClient = useQueryClient();
  const modes = useModes();
  const [busy, setBusy] = useState(null);
  const government = modes.data?.government;
  const demo = modes.data?.demo;

  async function toggle(kind, enabled) {
    setBusy(kind);
    try {
      await api(`/admin/${kind}-mode/toggle`, { method: "POST", json: { enabled } });
      await Promise.all([queryClient.invalidateQueries({ queryKey: keys.modes }), queryClient.invalidateQueries({ queryKey: keys.cameras })]);
      toast(`${kind === "government" ? "Government" : "Demo"} mode ${enabled ? "on" : "off"}`, { tone: "live" });
    } catch (error) {
      toast(`Couldn't change ${kind} mode`, { tone: "critical", detail: error.message });
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className={styles.block}>
      <SectionBar title="System" />
      <div className={`ui-card ${styles.settings}`}>
        <SettingRow
          icon={<FileVideo />}
          title="Government mode"
          description="Replay recorded government footage as live camera streams."
          status={government}
          busy={busy === "government"}
          onToggle={(enabled) => toggle("government", enabled)}
          detail={
            <span className={styles.settingDetail}>
              {government?.camera_ids?.length ?? 0} cameras on the relay
              {government?.degraded ? " · switch on again to repair" : ""}
            </span>
          }
        />
        <SettingRow
          icon={<Clapperboard />}
          title="Demo mode"
          description="Rehearsal cameras with synthetic footage and a sample watchlist plate."
          status={demo}
          busy={busy === "demo"}
          onToggle={(enabled) => toggle("demo", enabled)}
          detail={
            <span className={styles.settingDetail}>
              {demo?.camera_count ?? 0} cameras · plate {demo?.plate}
            </span>
          }
        />
      </div>
      <p className={styles.footnote}>Only one mode can be on at a time. Recorded footage is not a live deployment.</p>
    </section>
  );
}
