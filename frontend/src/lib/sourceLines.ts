// Quoting a Lore paste by the line numbers the backend sends with each
// moment (the plan event's source_lines). The rules match the backend's own
// numbering, set out in docs "Data this needs": number the exact string that
// was sent, after the 20,000-character cut, split on "\n" only, line 1 first.
// Blank lines keep their number but are never quoted.
//
// No imports, so `node --test` can run the tests on this file as it is.

/** The backend's max_dump_chars. Counted in code points, as Python does. */
export const MAX_DUMP_CHARS = 20000;

/** One quoted line. `speaker` is set only when the line plainly starts
 * with a short name and ": ". */
export interface QuotedLine {
  number: number;
  speaker: string | null;
  text: string;
}

/** The paste as the backend received it: the first 20,000 code points. */
export function cutText(sent: string): string {
  return Array.from(sent).slice(0, MAX_DUMP_CHARS).join("");
}

/** True when the paste is longer than the part that is used. */
export function isOverCut(sent: string): boolean {
  let n = 0;
  for (const _ of sent) {
    if (++n > MAX_DUMP_CHARS) return true;
  }
  return false;
}

/** Lines of the cut text. Index 0 is line 1. */
export function numberedLines(sent: string): string[] {
  return cutText(sent).split("\n");
}

const NAME = /^[^\d[\](){}<>:]{1,24}$/;

/**
 * Splits off a speaker name, and only when it is plainly one: the text
 * before the first ": " is short, has no digits or brackets, and has no
 * space at either end. A WhatsApp copy such as "[11/18/26, 9:41 PM] Maya:
 * hi" fails that test and is shown as is.
 */
export function splitSpeaker(line: string): { speaker: string | null; text: string } {
  const at = line.indexOf(": ");
  if (at <= 0) return { speaker: null, text: line };
  const name = line.slice(0, at);
  if (!NAME.test(name) || name.trim() !== name) return { speaker: null, text: line };
  return { speaker: name, text: line.slice(at + 2) };
}

/**
 * The lines one moment drew on, in order. Numbers that don't point at a
 * line, or point at a blank one, are skipped. Null when nothing is left,
 * which means "show the moment's summary instead".
 */
export function quoteLines(sent: string, numbers: readonly number[] | null | undefined): QuotedLine[] | null {
  if (!numbers || numbers.length === 0) return null;
  const lines = numberedLines(sent);
  const seen = new Set<number>();
  const quoted: QuotedLine[] = [];
  for (const n of [...numbers].sort((a, b) => a - b)) {
    if (!Number.isInteger(n) || n < 1 || n > lines.length || seen.has(n)) continue;
    seen.add(n);
    const line = lines[n - 1];
    if (line.trim() === "") continue;
    quoted.push({ number: n, ...splitSpeaker(line) });
  }
  return quoted.length > 0 ? quoted : null;
}

/**
 * The line numbers for entry `index` of a plan. A take reuses the lines of
 * the moment it retakes, so its row keeps the quote.
 */
export function linesForEntry(
  sourceLines: readonly (readonly number[] | null)[] | undefined,
  takeOf: readonly (number | null)[] | undefined,
  index: number,
): readonly number[] | null {
  if (!sourceLines) return null;
  const moment = takeOf?.[index] ?? index;
  return sourceLines[moment] ?? null;
}

/** The collapsed preview of a paste: its first non-blank lines, and how
 * many more non-blank lines there are. */
export function previewLines(text: string, shown = 3): { lines: QuotedLine[]; more: number } {
  const all = text
    .split("\n")
    .map((line, i) => ({ line, number: i + 1 }))
    .filter(({ line }) => line.trim() !== "");
  return {
    lines: all.slice(0, shown).map(({ line, number }) => ({ number, ...splitSpeaker(line) })),
    more: Math.max(0, all.length - shown),
  };
}

/** "7 more messages", or "1 more message". */
export function moreMessagesLabel(more: number): string {
  return `${more} more message${more === 1 ? "" : "s"}`;
}
