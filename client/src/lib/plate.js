/**
 * Groups an Indian registration mark for display the way it is stamped:
 * state · district · series · number (GJ 01 AB 1234). Anything that doesn't
 * fit the shape is shown exactly as read — the plate text itself is never
 * altered, only spaced.
 */
export function plateGroups(plate) {
  if (!plate) return [];
  const raw = String(plate).toUpperCase().replace(/[^A-Z0-9?]/g, "");
  const match = raw.match(/^([A-Z]{2})(\d{1,2})([A-Z]{0,3})(\d{1,4})(\??)$/);
  if (!match) return [raw];
  return [match[1], match[2], match[3], match[4] + match[5]].filter(Boolean);
}
