import { useAlerts } from "./AlertsContext.jsx";

export default function AlertsNavBadge() {
  const { openAlerts } = useAlerts();
  if (openAlerts.length === 0) return null;
  return <span className="nav-count-badge">{openAlerts.length}</span>;
}
