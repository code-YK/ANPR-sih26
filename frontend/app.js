const API = "/api";

let cameras = [];
let map = null;
let markers = [];

function toast(msg) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 2200);
}

async function api(path, opts = {}) {
  const resp = await fetch(API + path, opts);
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      detail = JSON.stringify(body.detail ?? body);
    } catch (_) {}
    throw new Error(`${resp.status}: ${detail}`);
  }
  const ct = resp.headers.get("content-type") || "";
  return ct.includes("application/json") ? resp.json() : resp.text();
}

// ---------- Navigation ----------

document.querySelectorAll(".nav-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".nav-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById("view-" + btn.dataset.view).classList.add("active");
    if (btn.dataset.view === "map") {
      initMapIfNeeded();
      renderMap();
    }
    if (btn.dataset.view === "gap") {
      loadGapReport();
    }
  });
});

// ---------- Camera list ----------

function badgeForLive(isLive) {
  if (isLive === true) return `<span class="badge badge-ok">live</span>`;
  if (isLive === false) return `<span class="badge badge-bad">offline</span>`;
  return `<span class="badge badge-muted">unknown</span>`;
}

function badgeForAnpr(v) {
  if (v === true) return `<span class="badge badge-ok">viable</span>`;
  if (v === false) return `<span class="badge badge-bad">not viable</span>`;
  return `<span class="badge badge-muted">not surveyed</span>`;
}

function badgeForGeocode(c) {
  if (c === "exact") return `<span class="badge badge-ok">exact</span>`;
  if (c === "approximate") return `<span class="badge badge-warn">approximate</span>`;
  if (c === "failed") return `<span class="badge badge-bad">unplaced</span>`;
  return `<span class="badge badge-muted">pending</span>`;
}

function metadataBadge(cam) {
  if (!cam.department && !cam.ownership && !cam.camera_type) return "";
  if (cam.metadata_confidence === "inferred") {
    return ` <span class="badge badge-inferred" title="Derived from a place-name guess, not a confirmed source">inferred</span>`;
  }
  if (cam.metadata_confidence === "confirmed") {
    return ` <span class="badge badge-confirmed">confirmed</span>`;
  }
  return "";
}

function renderCameraTable() {
  const dept = document.getElementById("filter-department").value;
  const anpr = document.getElementById("filter-anpr").value;
  const live = document.getElementById("filter-live").value;

  const rows = cameras.filter((c) => {
    if (dept && c.department !== dept) return false;
    if (anpr === "true" && c.anpr_viable !== true) return false;
    if (anpr === "false" && c.anpr_viable !== false) return false;
    if (anpr === "null" && c.anpr_viable !== null) return false;
    if (live === "true" && c.is_live !== true) return false;
    if (live === "false" && c.is_live !== false) return false;
    return true;
  });

  const tbody = document.getElementById("camera-table-body");
  tbody.innerHTML = rows
    .map(
      (c) => `
    <tr>
      <td>${c.camera_number}</td>
      <td>${c.name}</td>
      <td>${c.location_text}</td>
      <td>${c.department ?? "—"}${metadataBadge(c)}</td>
      <td>${badgeForLive(c.is_live)}</td>
      <td>${badgeForAnpr(c.anpr_viable)}</td>
      <td>${badgeForGeocode(c.geocode_confidence)}</td>
      <td>${c.transport_ok ?? "—"}</td>
      <td><button class="link-btn" data-edit="${c.camera_id}">Edit</button></td>
    </tr>`
    )
    .join("");

  tbody.querySelectorAll("[data-edit]").forEach((btn) => {
    btn.addEventListener("click", () => openEditModal(btn.dataset.edit));
  });
}

["filter-department", "filter-anpr", "filter-live"].forEach((id) =>
  document.getElementById(id).addEventListener("change", renderCameraTable)
);

async function loadCameras() {
  cameras = await api("/cameras");
  renderCameraTable();
}

document.getElementById("btn-resync").addEventListener("click", async () => {
  toast("Syncing catalogue…");
  try {
    const result = await api("/sync", { method: "POST" });
    toast(`Synced: ${result.fetched} fetched, ${result.inserted} new, ${result.updated} updated`);
    await loadCameras();
  } catch (e) {
    toast("Sync failed: " + e.message);
  }
});

// ---------- Location picker (shared by the edit and add-camera modals) ----------

const GUJARAT_CENTER = [22.6, 71.6];

// Lazily creates a small Leaflet map + draggable pin wired to a pair of
// lat/lng <input>s. Click the map or drag the pin to set the inputs;
// typing in the inputs moves the pin. The map is created once per modal
// (not per open) and just re-centred/re-sized on each .open() call, since
// Leaflet can't size itself correctly inside a container that was hidden
// (display:none) at construction time.
function createLocationPicker(mapDivId, latInput, lngInput) {
  let map = null;
  let marker = null;

  function placeMarker(lat, lng) {
    if (!marker) {
      marker = L.marker([lat, lng], { draggable: true }).addTo(map);
      marker.on("dragend", () => {
        const pos = marker.getLatLng();
        latInput.value = pos.lat.toFixed(6);
        lngInput.value = pos.lng.toFixed(6);
      });
    } else {
      marker.setLatLng([lat, lng]);
    }
  }

  function removeMarker() {
    if (marker) {
      map.removeLayer(marker);
      marker = null;
    }
  }

  function ensureMap() {
    if (map) return;
    map = L.map(mapDivId).setView(GUJARAT_CENTER, 7);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "&copy; OpenStreetMap contributors",
      maxZoom: 19,
    }).addTo(map);
    map.on("click", (e) => {
      latInput.value = e.latlng.lat.toFixed(6);
      lngInput.value = e.latlng.lng.toFixed(6);
      placeMarker(e.latlng.lat, e.latlng.lng);
    });

    // Bidirectional: typing coordinates in by hand also moves the pin.
    const syncFromInputs = () => {
      const lat = parseFloat(latInput.value);
      const lng = parseFloat(lngInput.value);
      if (!isNaN(lat) && !isNaN(lng)) {
        placeMarker(lat, lng);
        map.panTo([lat, lng]);
      } else if (latInput.value === "" && lngInput.value === "") {
        removeMarker();
      }
    };
    latInput.addEventListener("input", syncFromInputs);
    lngInput.addEventListener("input", syncFromInputs);
  }

  return {
    // Call after the modal is already visible (display != none), otherwise
    // Leaflet measures a zero-size container.
    open(lat, lng) {
      ensureMap();
      requestAnimationFrame(() => {
        map.invalidateSize();
        if (lat != null && lng != null) {
          map.setView([lat, lng], 14);
          placeMarker(lat, lng);
        } else {
          map.setView(GUJARAT_CENTER, 7);
          removeMarker();
        }
      });
    },
  };
}

const editLocationPicker = createLocationPicker(
  "edit-map",
  document.getElementById("edit-lat-input"),
  document.getElementById("edit-lng-input")
);
const createModalLocationPicker = createLocationPicker(
  "create-map",
  document.getElementById("create-lat-input"),
  document.getElementById("create-lng-input")
);

// ---------- Edit modal ----------

const modal = document.getElementById("edit-modal");
const form = document.getElementById("edit-form");
let editingCameraId = null;

function openEditModal(cameraId) {
  const cam = cameras.find((c) => c.camera_id === cameraId);
  if (!cam) return;
  editingCameraId = cameraId;
  document.getElementById("edit-modal-title").textContent = `Edit — ${cam.name} (${cam.location_text})`;
  form.department.value = cam.department ?? "";
  form.ownership.value = cam.ownership ?? "";
  form.camera_type.value = cam.camera_type ?? "";
  form.connectivity.value = cam.connectivity ?? "";
  form.storage_location.value = cam.storage_location ?? "";
  form.retention_days.value = cam.retention_days ?? "";
  form.metadata_confidence.value = cam.metadata_confidence ?? "";
  form.latitude.value = cam.latitude ?? "";
  form.longitude.value = cam.longitude ?? "";
  form.anpr_viable.value = cam.anpr_viable === true ? "true" : cam.anpr_viable === false ? "false" : "";
  form.anpr_notes.value = cam.anpr_notes ?? "";
  modal.classList.add("active");
  editLocationPicker.open(cam.latitude, cam.longitude);
}

document.getElementById("btn-cancel-edit").addEventListener("click", () => modal.classList.remove("active"));
modal.addEventListener("click", (e) => {
  if (e.target === modal) modal.classList.remove("active");
});

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(form);
  const payload = {};
  for (const [key, raw] of fd.entries()) {
    if (raw === "") continue;
    if (key === "retention_days") payload[key] = parseInt(raw, 10);
    else if (key === "latitude" || key === "longitude") payload[key] = parseFloat(raw);
    else if (key === "anpr_viable") payload[key] = raw === "true";
    else payload[key] = raw;
  }
  try {
    await api(`/cameras/${editingCameraId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    toast("Saved");
    modal.classList.remove("active");
    await loadCameras();
  } catch (err) {
    toast("Save failed: " + err.message);
  }
});

// ---------- Add camera (manual entry) modal ----------

const createModal = document.getElementById("create-modal");
const createForm = document.getElementById("create-form");

document.getElementById("btn-add-camera").addEventListener("click", () => {
  createForm.reset();
  createModal.classList.add("active");
  createModalLocationPicker.open(null, null);
});

document.getElementById("btn-cancel-create").addEventListener("click", () => createModal.classList.remove("active"));
createModal.addEventListener("click", (e) => {
  if (e.target === createModal) createModal.classList.remove("active");
});

createForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(createForm);
  const payload = {};
  for (const [key, raw] of fd.entries()) {
    if (raw === "") continue;
    if (key === "retention_days") payload[key] = parseInt(raw, 10);
    else if (key === "latitude" || key === "longitude") payload[key] = parseFloat(raw);
    else payload[key] = raw;
  }
  try {
    const created = await api("/cameras", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    toast(`Added ${created.camera_id} (#${created.camera_number})`);
    createModal.classList.remove("active");
    await loadCameras();
  } catch (err) {
    toast("Add camera failed: " + err.message);
  }
});

// ---------- Bulk CSV import ----------

document.getElementById("bulk-csv-input").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const fd = new FormData();
  fd.append("file", file);
  try {
    const result = await api("/cameras/bulk", { method: "POST", body: fd });
    toast(`Import: ${result.updated} updated, ${result.failed} failed (of ${result.total_rows})`);
    await loadCameras();
  } catch (err) {
    toast("Import failed: " + err.message);
  }
  e.target.value = "";
});

// ---------- Map ----------

function initMapIfNeeded() {
  if (map) return;
  map = L.map("map").setView([22.6, 71.6], 7); // roughly centred on Gujarat
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap contributors",
    maxZoom: 19,
  }).addTo(map);
}

function anprColor(v) {
  if (v === true) return "#1b7a3d";
  if (v === false) return "#b3261e";
  return "#8a8f98";
}

function renderMap() {
  const dept = document.getElementById("map-filter-department").value;
  const anpr = document.getElementById("map-filter-anpr").value;
  const live = document.getElementById("map-filter-live").value;

  markers.forEach((m) => map.removeLayer(m));
  markers = [];

  const placed = [];
  const unplaced = [];

  cameras.forEach((c) => {
    if (dept && c.department !== dept) return;
    if (anpr === "true" && c.anpr_viable !== true) return;
    if (anpr === "false" && c.anpr_viable !== false) return;
    if (live === "true" && c.is_live !== true) return;
    if (live === "false" && c.is_live !== false) return;

    if (c.latitude != null && c.longitude != null) placed.push(c);
    else unplaced.push(c);
  });

  placed.forEach((c) => {
    const marker = L.circleMarker([c.latitude, c.longitude], {
      radius: 7,
      color: anprColor(c.anpr_viable),
      fillColor: anprColor(c.anpr_viable),
      fillOpacity: 0.75,
      weight: 2,
    }).addTo(map);
    marker.bindPopup(`
      <strong>${c.name}</strong><br>
      ${c.location_text}<br>
      Department: ${c.department ?? "—"}<br>
      ANPR: ${c.anpr_viable === true ? "viable" : c.anpr_viable === false ? "not viable" : "not surveyed"}<br>
      Live: ${c.is_live ? "yes" : "no"}<br>
      Geocode: ${c.geocode_confidence ?? "pending"}
    `);
    markers.push(marker);
  });

  const unplacedEl = document.getElementById("unplaced-list");
  unplacedEl.innerHTML = unplaced.length
    ? unplaced
        .map(
          (c) => `<div class="cam-row"><strong>${c.name}</strong><div class="loc">${c.location_text} — ${
            c.geocode_confidence === "failed" ? "geocode failed" : "not yet geocoded"
          }</div></div>`
        )
        .join("")
    : `<div class="cam-row loc">None — every filtered camera is placed.</div>`;
}

["map-filter-department", "map-filter-anpr", "map-filter-live"].forEach((id) =>
  document.getElementById(id).addEventListener("change", renderMap)
);

// ---------- Gap analysis ----------

function loadGapReport() {
  document.getElementById("gap-frame").src = API + "/gap-analysis/export?format=html";
}
document.getElementById("btn-gap-refresh").addEventListener("click", loadGapReport);
document.getElementById("btn-gap-pdf").addEventListener("click", () => {
  window.open(API + "/gap-analysis/export?format=pdf", "_blank");
});

// ---------- Init ----------

loadCameras();
