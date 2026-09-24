import { plateGroups } from "../lib/plate.js";

/**
 * A registration mark as the physical stamped object it is (DESIGN.md §5.1),
 * grouped the way it is stamped by lib/plate.js.
 *
 * A read the plate reader has not confirmed keeps the worker's own trailing
 * "?" and takes the dashed, faced-down treatment: a plate the model is still
 * unsure about must never look like one it has settled. Tentative is detected
 * from the text itself, so the same component is correct whether the string
 * came from a sighting (always confirmed) or from live telemetry (either).
 *
 * The class names are the ones the Alerts view introduced. Shared rather than
 * duplicated -- a second set of plate styles is how two plates start looking
 * different in two places.
 */
export default function PlateChip({ plate, className = "", title }) {
  if (!plate) return <span className="detector-plate-absent">—</span>;
  const text = String(plate);
  const tentative = text.endsWith("?");
  const classes = [
    "alerts-plate-chip",
    tentative ? "alerts-plate-chip--tentative" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <span
      className={classes}
      title={title}
      aria-label={`Plate ${text.replace("?", "")}${tentative ? ", tentative" : ""}`}
    >
      <span className="alerts-plate-chip-stripe" aria-hidden="true">
        IND
      </span>
      <span className="alerts-plate-chip-text" aria-hidden="true">
        {plateGroups(text).map((group, index) => (
          <span key={index}>{group}</span>
        ))}
      </span>
    </span>
  );
}
