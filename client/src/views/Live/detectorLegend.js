/**
 * What the detector view's pixels mean, and which model drew them.
 *
 * Every colour here is transcribed from the worker that actually draws the
 * boxes, not chosen for the console -- a legend that disagrees with the frame
 * is worse than no legend. OpenCV literals are BGR, so each one is reversed
 * to RGB below and the source line is named so the two can be re-checked
 * together:
 *
 *   vehicle modes  multi-object-tracking/observation_worker.py
 *                  VEHICLE_COLORS_BY_NAME
 *   plate borders  multi-object-tracking/worker_telemetry.py
 *                  PLATE_CONFIRMED_BGR / PLATE_TENTATIVE_BGR
 *   person         multi-object-tracking/person_observation_worker.py
 *                  class_colors={PERSON_CLASS_ID: (0, 220, 255)}
 *   suspicious     multi-object-tracking/suspicious_observation_worker.py
 *                  TELEMETRY_COLORS
 *
 * These swatches are the one place the console shows colour that is not
 * urgency (DESIGN.md §4 reserves colour for urgency alone). The exception is
 * deliberate and narrow: the colours already exist in the video frame, drawn
 * by the model, and the legend's whole job is to decode them. Nothing else in
 * this feature introduces a hue.
 */

// auto_rickshaw exists only in the fine-tuned checkpoint's own class list;
// the baseline is COCO, which has no such class (see build_vehicle_maps).
const VEHICLE_CLASSES = [
  { cls: "car", label: "Car", color: "#ffc800" },                // BGR (0, 200, 255)
  { cls: "motorcycle", label: "Motorcycle", color: "#0064ff" },   // BGR (255, 100, 0)
  { cls: "bus", label: "Bus", color: "#64ff00" },                 // BGR (0, 255, 100)
  { cls: "truck", label: "Truck", color: "#ff0064" },             // BGR (100, 0, 255)
];
const AUTO_RICKSHAW = { cls: "auto_rickshaw", label: "Auto-rickshaw", color: "#ff00b4" }; // BGR (180, 0, 255)

// Drawn at the plate itself, not the vehicle: solid white chip with a green
// rule when the per-character vote has settled, a softer amber outline with a
// trailing "?" while it has not. The second is never recorded as a sighting.
const PLATE_MARKS = [
  { label: "Confirmed plate", color: "#3cc83c", shape: "plate" },      // BGR (60, 200, 60)
  { label: "Reading — tentative “?”", color: "#ffaa00", shape: "dashed" }, // BGR (0, 170, 255)
];

/**
 * One entry per backend worker mode. `family` groups the two vehicle modes,
 * which differ only in checkpoint: the console shows both under one ANPR tab.
 */
export const MODE_META = {
  vehicle_finetuned: {
    mode: "vehicle_finetuned",
    family: "vehicle",
    tab: "anpr",
    label: "ANPR",
    title: "Number plate recognition",
    model: "Fine-tuned veh5 · plate OCR",
    legend: [...VEHICLE_CLASSES, AUTO_RICKSHAW, ...PLATE_MARKS],
  },
  vehicle: {
    mode: "vehicle",
    family: "vehicle",
    tab: "anpr",
    label: "ANPR",
    title: "Number plate recognition",
    model: "Baseline yolo11x · plate OCR",
    legend: [...VEHICLE_CLASSES, ...PLATE_MARKS],
  },
  person: {
    mode: "person",
    family: "person",
    tab: "person",
    label: "Person",
    title: "Person detection and counting",
    model: "yolo11n · tracked 30s windows",
    legend: [{ cls: "person", label: "Person", color: "#ffdc00" }], // BGR (0, 220, 255)
  },
  suspicious: {
    mode: "suspicious",
    family: "suspicious",
    tab: "suspicious",
    label: "Suspicious",
    title: "Suspicious-activity detection",
    model: "Two-class person model · 3-frame confirmation",
    legend: [
      { cls: "person", label: "Person", color: "#00c800" },              // BGR (0, 200, 0)
      { cls: "DANGER", label: "Potentially dangerous", color: "#ff0000" }, // BGR (0, 0, 255)
    ],
  },
};

/**
 * The two ANPR checkpoints, in the order the dropdown lists them. The
 * fine-tuned one is the default everywhere.
 *
 * They are mutually exclusive per camera: one vehicle-family detector per
 * camera at a time, enforced server-side in cameras.py's
 * _apply_operator_update as well as here, because this hardware has no GPU
 * headroom for two yolo11x-class workers on one feed. `column` is the
 * persistent intent the auto-start supervisor reconciles; setting it needs
 * camera-administrator access, which is why starting a worker directly is a
 * separate, operator-level action (see DetectorWorkbench.startMode).
 */
export const ANPR_MODELS = [
  {
    mode: "vehicle_finetuned",
    label: "Fine-tuned",
    detail: "veh5 checkpoint · adds auto-rickshaw",
    column: "analytics_finetuned_enabled",
    other: "vehicle",
    otherColumn: "analytics_enabled",
    isDefault: true,
  },
  {
    mode: "vehicle",
    label: "Baseline",
    detail: "stock yolo11x · COCO classes",
    column: "analytics_enabled",
    other: "vehicle_finetuned",
    otherColumn: "analytics_finetuned_enabled",
    isDefault: false,
  },
];

export const DEFAULT_ANPR_MODE = "vehicle_finetuned";

/** Tabs, left to right, as the header renders them. */
export const TABS = [
  { id: "anpr", label: "ANPR" },
  { id: "person", label: "Person" },
  { id: "suspicious", label: "Suspicious" },
];

/** Backend worker mode for a tab, given the operator's ANPR model choice. */
export function modeForTab(tab, anprMode = DEFAULT_ANPR_MODE) {
  if (tab === "anpr") return anprMode;
  return tab;
}

/** Tab a backend worker mode belongs to. */
export function tabForMode(mode) {
  return MODE_META[mode]?.tab ?? "anpr";
}

export function legendFor(mode) {
  return MODE_META[mode]?.legend ?? [];
}

/**
 * How a mode's per-class counts should be labelled and coloured, in legend
 * order. `counts` is the worker's own `in_frame_by_class` / `unique_by_class`
 * map, keyed by its class names -- a class the model never reported is absent
 * rather than shown as a zero, and a class the legend does not know about
 * (a checkpoint with a class this console predates) still appears, uncoloured
 * and under its raw name, rather than being silently dropped.
 */
export function classRows(mode, counts) {
  const legend = legendFor(mode).filter((item) => item.cls);
  const seen = new Set();
  const rows = [];
  for (const item of legend) {
    const value = counts?.[item.cls];
    seen.add(item.cls);
    if (value) rows.push({ key: item.cls, label: item.label, color: item.color, value });
  }
  for (const [cls, value] of Object.entries(counts ?? {})) {
    if (seen.has(cls) || !value) continue;
    rows.push({ key: cls, label: cls.replace(/_/g, " "), color: null, value });
  }
  return rows;
}
