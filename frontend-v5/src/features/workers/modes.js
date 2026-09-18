/**
 * The three AI inference modes the console exposes, mapped onto the backend's
 * worker modes. ANPR runs the fine-tuned veh5 checkpoint (`vehicle_finetuned`)
 * whose on/off intent is a persistent camera column the backend supervisor
 * reconciles every 10s -- so it is started by setting that column first, and
 * stopped by clearing it first. Person and Suspicious are plain start/stop.
 */
export const MODES = {
  anpr: {
    key: "anpr",
    label: "ANPR",
    title: "Number plate recognition",
    backendMode: "vehicle_finetuned",
    intentColumn: "analytics_finetuned_enabled",
    conflictBackendMode: "vehicle",
    conflictIntentColumn: "analytics_enabled",
    queueable: true,
    requiresCameraAdmin: true,
    model: "Fine-tuned YOLO11x · plate OCR",
    legend: [
      { label: "Car", color: "var(--det-car)" },
      { label: "Motorcycle", color: "var(--det-motorcycle)" },
      { label: "Bus", color: "var(--det-bus)" },
      { label: "Truck", color: "var(--det-truck)" },
      { label: "Auto-rickshaw", color: "var(--det-auto)" },
    ],
  },
  person: {
    key: "person",
    label: "Person",
    title: "Person detection and counting",
    backendMode: "person",
    queueable: false,
    requiresCameraAdmin: false,
    model: "YOLO11n · tracked counts",
    legend: [{ label: "Person", color: "var(--det-person)" }],
  },
  suspicious: {
    key: "suspicious",
    label: "Suspicious",
    title: "Suspicious-activity detection",
    backendMode: "suspicious",
    queueable: false,
    requiresCameraAdmin: false,
    model: "Two-class person model · 3-frame confirmation",
    legend: [
      { label: "Person", color: "var(--det-person)" },
      { label: "Potentially dangerous", color: "var(--det-danger)" },
    ],
  },
};

export const MODE_KEYS = ["anpr", "person", "suspicious"];

/** Backend worker mode -> console mode key. `vehicle` is the legacy baseline. */
export const BACKEND_TO_MODE = {
  vehicle_finetuned: "anpr",
  person: "person",
  suspicious: "suspicious",
  vehicle: "anpr-baseline",
};

export const BACKEND_LABEL = {
  vehicle_finetuned: "ANPR",
  vehicle: "ANPR (baseline model)",
  person: "Person",
  suspicious: "Suspicious",
};

export function workerId(cameraId, modeKey) {
  return `${cameraId}::${modeKey}`;
}

export function rowWorkerId(row) {
  return workerId(row.camera_id, BACKEND_TO_MODE[row.mode] ?? row.mode);
}
