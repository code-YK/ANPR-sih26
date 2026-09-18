/**
 * Pure notification rules: lifetime, grouping, replacement, what is visible,
 * and when a sound may play. Kept free of React so they can be tested.
 */

export const TTL_MS = {
  sighting: 6_500,
  "sighting-group": 8_000,
  watchlist: 12_000,
  suspicious: 12_000,
  worker: 9_000,
  system: 4_000,
};

export const MAX_VISIBLE = 3;
export const MAX_ITEMS = 30;
/** This many sightings from one camera inside the window collapse into one card. */
export const GROUP_THRESHOLD = 3;
export const GROUP_WINDOW_MS = 5_000;

export const SOUND_GAP_MS = { sighting: 3_000, alert: 1_500 };

let counter = 0;

function nextId(kind, now) {
  counter += 1;
  return `${kind}-${now}-${counter}`;
}

function sightingKeysOf(item) {
  return item.sightingKeys ?? (item.key ? [item.key] : []);
}

/**
 * Adds one notification, applying replacement (an alert supersedes the card
 * for the sighting that raised it), de-duplication by `key`, and per-camera
 * grouping of sighting bursts. Returns a new array; newest last.
 */
export function addNotification(items, input, now) {
  const item = {
    id: nextId(input.kind, now),
    createdAt: now,
    ttl: TTL_MS[input.kind] ?? 6_000,
    count: 1,
    ...input,
  };

  let next = items;

  if (item.replaces) {
    next = next
      .map((existing) => {
        if (existing.kind !== "sighting-group" || !existing.sightingKeys?.includes(item.replaces)) return existing;
        const sightingKeys = existing.sightingKeys.filter((key) => key !== item.replaces);
        return { ...existing, sightingKeys, count: Math.max(0, existing.count - 1) };
      })
      .filter((existing) => existing.key !== item.replaces && !(existing.kind === "sighting-group" && existing.count === 0));
  }

  if (item.key && next.some((existing) => existing.key === item.key || existing.sightingKeys?.includes(item.key))) {
    return next;
  }

  if (item.kind === "sighting") {
    const recent = next.filter(
      (existing) =>
        (existing.kind === "sighting" || existing.kind === "sighting-group") &&
        existing.cameraId === item.cameraId &&
        now - existing.createdAt < GROUP_WINDOW_MS,
    );
    const recentCount = recent.reduce((sum, existing) => sum + (existing.count || 1), 0);
    if (recent.length > 0 && recentCount + 1 >= GROUP_THRESHOLD) {
      const plates = [item.plate, ...recent.slice().reverse().flatMap((existing) => existing.plates ?? [existing.plate])]
        .filter(Boolean)
        .slice(0, 3);
      const group = {
        id: nextId("sighting-group", now),
        kind: "sighting-group",
        createdAt: now,
        ttl: TTL_MS["sighting-group"],
        cameraId: item.cameraId,
        cameraName: item.cameraName,
        href: item.href,
        time: item.time,
        count: recentCount + 1,
        plates,
        sightingKeys: [item.key, ...recent.flatMap(sightingKeysOf)].filter(Boolean),
      };
      next = next.filter((existing) => !recent.includes(existing));
      return trim([...next, group]);
    }
  }

  return trim([...next, item]);
}

function trim(items) {
  return items.length > MAX_ITEMS ? items.slice(items.length - MAX_ITEMS) : items;
}

/** The newest `max` are shown; the rest are summarised as an overflow count. */
export function splitVisible(items, max = MAX_VISIBLE) {
  const visible = items.length > max ? items.slice(items.length - max) : items;
  return { visible, overflow: items.length - visible.length };
}

export function soundFor(kind) {
  if (kind === "watchlist" || kind === "suspicious") return "alert";
  if (kind === "sighting" || kind === "sighting-group") return "sighting";
  return null;
}

/** Rate limit per sound so a burst of events makes one sound, not many. */
export function shouldPlaySound(sound, lastPlayedAt, now) {
  if (!sound) return false;
  const last = lastPlayedAt[sound];
  return last == null || now - last >= SOUND_GAP_MS[sound];
}
