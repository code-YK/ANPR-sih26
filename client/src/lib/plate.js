/**
 * Groups an Indian registration mark for display the way it is stamped:
 *   state · district · series · number        GJ 01 AB 1234
 *   Delhi: state · district+category · number DL 2CBB 4791, DL 10CN 7685
 *   Bharat series: year · BH · number · series 22 BH 1234 AA
 * Anything that doesn't fit is shown exactly as read — the plate text itself
 * is never altered, only spaced. A trailing "?" (tentative read) stays on the
 * last group.
 */
export function plateGroups(plate) {
  if (!plate) return [];
  const raw = String(plate).toUpperCase().replace(/[^A-Z0-9?]/g, "");
  const tentative = raw.endsWith("?") ? "?" : "";
  const text = tentative ? raw.slice(0, -1) : raw;
  const bharat = text.match(/^(\d{2})(BH)(\d{4})([A-Z]{1,2})$/);
  if (bharat) return [bharat[1], bharat[2], bharat[3], bharat[4] + tentative];
  const delhi = text.match(/^(DL)(\d{1,2}[A-Z]{1,3})(\d{4})$/);
  if (delhi) return [delhi[1], delhi[2], delhi[3] + tentative];
  const match = text.match(/^([A-Z]{2})(\d{1,2})([A-Z]{0,3})(\d{1,4})$/);
  if (!match) return [raw];
  return [match[1], match[2], match[3], match[4] + tentative].filter(Boolean);
}
