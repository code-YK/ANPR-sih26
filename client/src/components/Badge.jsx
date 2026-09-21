// The certainty grammar (DESIGN.md §3.1/§7): texture carries how a fact is
// known, colour carries urgency, and the two never mix. Four states --
// confirmed, inferred, unknown, withheld -- rendered identically wherever
// they appear, each paired with a plain word except confirmed, which is the
// default and stays silent. This replaces the four ad-hoc badge-* pills this
// file used to export. `LiveBadge` is deliberately labelled as a catalogue
// claim: only an active browser player can say it has actually connected.
//
// `withheld` has no call site yet: nothing in the current API marks a field
// as hidden-by-grant rather than merely absent (the journey endpoint's
// restricted_stops is a row-level count, not a per-field signal). The
// variant is built and ready for whenever a real one exists -- not wired to
// a fake one now.

export function CertaintyMark({ state, value, label, title }) {
  if (state === "confirmed") {
    return <span className="certainty certainty-confirmed">{value}</span>;
  }
  if (state === "inferred") {
    return (
      <span className="certainty certainty-inferred" title={title}>
        {value && <span className="certainty-value">{value}</span>}
        <span className="certainty-label">{label}</span>
      </span>
    );
  }
  if (state === "withheld") {
    return (
      <span className="certainty certainty-withheld" title={title}>
        <span className="certainty-hatch" aria-hidden="true" />
        <span className="certainty-label">{label}</span>
      </span>
    );
  }
  // unknown
  return (
    <span className="certainty certainty-unknown" title={title}>
      <span className="certainty-value" aria-hidden="true">—</span>
      <span className="certainty-label">{label}</span>
    </span>
  );
}

export function LiveBadge({ value }) {
  if (value === true) return <span className="badge badge-ok" title="Reported by the source catalogue; it does not confirm current browser playback">source live</span>;
  if (value === false) return <span className="badge badge-bad" title="Reported by the source catalogue">source offline</span>;
  return <CertaintyMark state="unknown" label="source unknown" />;
}

export function PlaybackBadge({ state }) {
  if (state === "connected") return <span className="badge badge-ok" title="This browser has buffered a media fragment from the authenticated relay">connected</span>;
  if (state === "connecting") return <span className="badge badge-warn">connecting</span>;
  if (state === "reconnecting") return <span className="badge badge-warn">reconnecting</span>;
  return null;
}

// Viable/not-viable are both settled, surveyed facts -- confirmed, not
// urgent -- so neither gets a colour; the thing worth an operator's eye is
// whether a camera was surveyed at all, which is what pops via the unknown
// texture. See DESIGN.md §7.
export function AnprBadge({ value }) {
  if (value === true) return <CertaintyMark state="confirmed" value="viable" />;
  if (value === false) return <CertaintyMark state="confirmed" value="not viable" />;
  return <CertaintyMark state="unknown" label="not surveyed" />;
}

export function GeocodeBadge({ value }) {
  if (value === "exact") return <CertaintyMark state="confirmed" value="exact" />;
  if (value === "approximate") {
    return (
      <CertaintyMark
        state="inferred"
        value="approximate"
        label="inferred"
        title="Estimated from a place name, not a surveyed coordinate"
      />
    );
  }
  if (value === "failed") return <CertaintyMark state="unknown" label="unplaced" />;
  return <CertaintyMark state="unknown" label="pending" />;
}

// Confirmed metadata renders nothing -- the department/type/ownership text
// next to this mark, left plain, already says "this is a trusted fact."
// Only the inferred case earns an annotation.
export function MetadataBadge({ camera }) {
  if (!camera.department && !camera.ownership && !camera.camera_type) return null;
  if (camera.metadata_confidence === "inferred") {
    return (
      <CertaintyMark
        state="inferred"
        label="inferred"
        title="Derived from a place-name guess, not a confirmed source"
      />
    );
  }
  return null;
}
