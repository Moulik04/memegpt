// Arc's story text, worded the way the server-drawn share card words it
// (backend/image_processing/compositor.py, _arc_date_span and
// _arc_season_line), so frame 01 and the card always agree.

const MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];

/** "2026-11-17" as its parts, with no time zone in play: the backend has
 * already turned the records into the visitor's own dates. */
function parts(iso: string): { year: number; month: number; day: number } {
  const [year, month, day] = iso.split("-").map(Number);
  return { year, month, day };
}

const monthDay = (d: { month: number; day: number }) => `${MONTHS[d.month - 1]} ${d.day}`;

/** "SEP 3–NOV 17, 2026", "DEC 20, 2026–FEB 10, 2027" or "NOV 17, 2026". */
export function arcDateSpan(startIso: string, endIso: string): string {
  const start = parts(startIso);
  const end = parts(endIso);
  if (startIso === endIso) return `${monthDay(end)}, ${end.year}`;
  if (start.year === end.year) return `${monthDay(start)}–${monthDay(end)}, ${end.year}`;
  return `${monthDay(start)}, ${start.year}–${monthDay(end)}, ${end.year}`;
}

/** "AUTUMN ARC • SEP 3–NOV 17, 2026", or just "YOUR ARC" without dates.
 * The label is the backend's (arc/copy.py), upper-cased. */
export function arcSeasonLine(periodLabel: string | null, startIso: string | null, endIso: string | null): string {
  const label = (periodLabel || "Your Arc").toUpperCase();
  if (!startIso || !endIso) return label;
  return `${label} • ${arcDateSpan(startIso, endIso)}`;
}

export interface Rung {
  name: string;
  min_aura: number;
}

/** Where a score sits on the ladder (top tier first, as GET /arc sends
 * it): the current rung's index, and the next rung up with the aura still
 * needed, or null at the top. */
export function ladderPosition(
  tiers: Rung[],
  tier: string | null,
  aura: number,
): { index: number; next: { name: string; distance: number } | null } {
  const index = tiers.findIndex((t) => t.name === tier);
  if (index <= 0) return { index, next: null };
  const above = tiers[index - 1];
  return { index, next: { name: above.name, distance: Math.max(0, above.min_aura - aura) } };
}

export const timesLabel = (n: number) => `${n.toLocaleString("en-US")} ${n === 1 ? "time" : "times"}`;
export const daysLabel = (n: number) => `${n.toLocaleString("en-US")} ${n === 1 ? "day" : "days"}`;
