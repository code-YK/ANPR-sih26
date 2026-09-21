import { useEffect, useState } from "react";

import { api } from "../../api.js";
import Modal from "../../components/Modal.jsx";
import { useToast } from "../../components/Toast.jsx";

const SEVERITIES = ["low", "medium", "high"];

const emptyForm = { raw_value: "", reason_code: "", severity: "medium", notes: "", source: "", active: true };

// `entry` is null for "create new", an object for "edit existing". Editing
// only touches metadata (reason/severity/notes/source/active) -- the
// backend's PUT doesn't allow changing raw_value/normalised_value after
// creation, so that field is read-only once an entry exists.
export default function WatchlistEntryModal({ open, entry, onClose, onSaved }) {
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);
  const showToast = useToast();
  const isEdit = !!entry;

  useEffect(() => {
    if (entry) {
      setForm({
        raw_value: entry.raw_value,
        reason_code: entry.reason_code ?? "",
        severity: entry.severity,
        notes: entry.notes ?? "",
        source: entry.source ?? "",
        active: entry.active,
      });
    } else {
      setForm(emptyForm);
    }
  }, [entry, open]);

  function set(field, value) {
    setForm((f) => ({ ...f, [field]: value }));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setSaving(true);
    try {
      if (isEdit) {
        await api(`/watchlist/${entry.id}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            reason_code: form.reason_code || null,
            severity: form.severity,
            notes: form.notes || null,
            source: form.source || null,
            active: form.active,
          }),
        });
        showToast("Saved");
      } else {
        await api("/watchlist", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            raw_value: form.raw_value,
            reason_code: form.reason_code || undefined,
            severity: form.severity,
            notes: form.notes || undefined,
            source: form.source || undefined,
            active: form.active,
          }),
        });
        showToast("Added to watchlist");
      }
      onClose();
      await onSaved();
    } catch (err) {
      showToast("Save failed: " + err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal open={open} onClose={onClose}>
      <h2>{isEdit ? `Edit — ${entry.raw_value}` : "Add watchlist entry"}</h2>
      <form onSubmit={handleSubmit}>
        <div className="field">
          <label>Plate / value {!isEdit && "*"}</label>
          <input
            required={!isEdit}
            disabled={isEdit}
            value={form.raw_value}
            onChange={(e) => set("raw_value", e.target.value)}
            placeholder="e.g. TESTPLATE001"
          />
          {isEdit && <div className="hint">The plate value can't be changed after creation — remove and re-add instead.</div>}
        </div>
        <div className="field">
          <label>Reason</label>
          <input
            value={form.reason_code}
            onChange={(e) => set("reason_code", e.target.value)}
            placeholder="e.g. stolen_vehicle"
          />
        </div>
        <div className="row2">
          <div className="field">
            <label>Severity</label>
            <select value={form.severity} onChange={(e) => set("severity", e.target.value)}>
              {SEVERITIES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>Source</label>
            <input value={form.source} onChange={(e) => set("source", e.target.value)} placeholder="e.g. eGujCop demo seed" />
          </div>
        </div>
        <div className="field">
          <label>Notes</label>
          <textarea rows={2} value={form.notes} onChange={(e) => set("notes", e.target.value)} />
        </div>
        <div className="field">
          <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input type="checkbox" checked={form.active} onChange={(e) => set("active", e.target.checked)} />
            Active (matches new sightings)
          </label>
        </div>
        <div className="actions">
          <button type="button" className="secondary" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="primary" disabled={saving}>
            {isEdit ? "Save" : "Add"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
