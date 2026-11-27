// Run by `npm test` and by prebuild: node --test, no test framework.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  MAX_DUMP_CHARS,
  cutText,
  isOverCut,
  linesForEntry,
  moreMessagesLabel,
  previewLines,
  quoteLines,
  splitSpeaker,
} from "./sourceLines.ts";

// The shared group chat from the handoff, section 7.3.
const CHAT = [
  "Maya: Flight delayed again. Third time.",
  "Leo: That gate has your mail now.",
  "June: This meeting could've been an email.",
  "You: It has a follow-up meeting.",
  "Leo: Do we get an agenda?",
  "June: I haven't started the essay.",
  "You: It's due tomorrow. Opening the doc at 11:58.",
  "Maya: Phone's at 1%.",
  "Leo: You sent that with one percent?",
  "Maya: I'm committed to the bit.",
].join("\n");

const texts = (q: ReturnType<typeof quoteLines>) => q?.map((l) => `${l.speaker}|${l.text}`) ?? null;

test("the four moments quote their own lines", () => {
  const plan = [[1, 2], [3, 4, 5], [6, 7], [8, 9, 10]];
  assert.deepEqual(texts(quoteLines(CHAT, plan[0])), [
    "Maya|Flight delayed again. Third time.",
    "Leo|That gate has your mail now.",
  ]);
  assert.deepEqual(texts(quoteLines(CHAT, plan[2])), [
    "June|I haven't started the essay.",
    "You|It's due tomorrow. Opening the doc at 11:58.",
  ]);
  assert.equal(quoteLines(CHAT, plan[3])?.length, 3);
});

test("null, empty and out-of-range numbers fall back to the summary", () => {
  assert.equal(quoteLines(CHAT, null), null);
  assert.equal(quoteLines(CHAT, []), null);
  assert.equal(quoteLines(CHAT, [0, 11, 99]), null);
  assert.deepEqual(
    quoteLines(CHAT, [11, 2, 2])?.map((l) => l.number),
    [2],
  );
});

test("blank lines keep their number but are never quoted", () => {
  const sent = "Maya: one\n\nLeo: three";
  assert.deepEqual(
    quoteLines(sent, [1, 2, 3])?.map((l) => l.number),
    [1, 3],
  );
  assert.equal(quoteLines(sent, [2]), null);
});

test("lines split on \\n only, so a \\r stays part of the line", () => {
  const q = quoteLines("Maya: one\r\nLeo: two", [1]);
  assert.equal(q?.[0].text, "one\r");
});

test("leading spaces stay part of the line and stop speaker bolding", () => {
  const q = quoteLines("  Maya: indented", [1]);
  assert.deepEqual(q?.[0], { number: 1, speaker: null, text: "  Maya: indented" });
});

test("the cut counts code points, not UTF-16 units", () => {
  const emoji = "😀";
  const sent = "a".repeat(MAX_DUMP_CHARS - 1) + emoji + "b";
  assert.equal(Array.from(cutText(sent)).length, MAX_DUMP_CHARS);
  assert.ok(cutText(sent).endsWith(emoji));
  assert.equal(isOverCut(sent), true);
  assert.equal(isOverCut("a".repeat(MAX_DUMP_CHARS)), false);
});

test("a line past the cut is never quoted", () => {
  const sent = "a".repeat(MAX_DUMP_CHARS) + "\nMaya: after the cut";
  assert.equal(quoteLines(sent, [2]), null);
});

test("speaker names are bolded only when plainly a name", () => {
  assert.deepEqual(splitSpeaker("Maya: hi"), { speaker: "Maya", text: "hi" });
  assert.deepEqual(splitSpeaker("Mary Jo: hi"), { speaker: "Mary Jo", text: "hi" });
  const whatsapp = "[11/18/26, 9:41 PM] Maya: Flight delayed again.";
  assert.deepEqual(splitSpeaker(whatsapp), { speaker: null, text: whatsapp });
  assert.equal(splitSpeaker("Note 2: hi").speaker, null);
  assert.equal(splitSpeaker("Maya (work): hi").speaker, null);
  assert.equal(splitSpeaker("a very long run of words that is surely not a name: hi").speaker, null);
  assert.equal(splitSpeaker("no colon here").speaker, null);
  assert.equal(splitSpeaker(": starts with one").speaker, null);
  assert.equal(splitSpeaker("Time:12").speaker, null);
});

test("a take reuses the lines of the moment it retakes", () => {
  const sourceLines = [[1, 2], [3, 4, 5], null];
  const takeOf = [null, null, 0];
  assert.deepEqual(linesForEntry(sourceLines, takeOf, 2), [1, 2]);
  assert.deepEqual(linesForEntry(sourceLines, takeOf, 1), [3, 4, 5]);
  assert.equal(linesForEntry(undefined, takeOf, 0), null);
  assert.equal(linesForEntry([null], undefined, 0), null);
});

test("the collapsed preview shows three lines and counts the rest", () => {
  const { lines, more } = previewLines(CHAT);
  assert.deepEqual(lines.map((l) => l.speaker), ["Maya", "Leo", "June"]);
  assert.equal(more, 7);
  assert.equal(moreMessagesLabel(more), "7 more messages");
  assert.equal(moreMessagesLabel(1), "1 more message");
  assert.equal(previewLines("one\n\ntwo").more, 0);
});
