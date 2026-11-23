// Run by `npm test` and by prebuild: node --test, no test framework.
import { test } from "node:test";
import assert from "node:assert/strict";
import { arcDateSpan, arcSeasonLine, daysLabel, ladderPosition, timesLabel } from "./arcFormat.ts";

// The backend sends these, top tier first (arc/copy.py, _tier_ladder).
const TIERS = [
  { name: "aura farming god", min_aura: 20_000 },
  { name: "baby aura farmer", min_aura: 17_501 },
  { name: "certified menace", min_aura: 10_000 },
  { name: "main character (unwell)", min_aura: 5_000 },
  { name: "side character energy", min_aura: 2_000 },
  { name: "npc arc", min_aura: 0 },
];

test("date spans read like the share card's", () => {
  assert.equal(arcDateSpan("2026-09-03", "2026-11-17"), "SEP 3–NOV 17, 2026");
  assert.equal(arcDateSpan("2026-11-03", "2026-11-17"), "NOV 3–NOV 17, 2026");
  assert.equal(arcDateSpan("2026-12-20", "2027-02-10"), "DEC 20, 2026–FEB 10, 2027");
  assert.equal(arcDateSpan("2026-11-17", "2026-11-17"), "NOV 17, 2026");
});

test("the season line takes the backend's label, or YOUR ARC", () => {
  assert.equal(arcSeasonLine("Autumn Arc", "2026-09-03", "2026-11-17"), "AUTUMN ARC • SEP 3–NOV 17, 2026");
  assert.equal(arcSeasonLine("Your Arc", "2026-06-02", "2026-11-17"), "YOUR ARC • JUN 2–NOV 17, 2026");
  assert.equal(arcSeasonLine(null, null, null), "YOUR ARC");
});

test("the handoff sample is 5,021 from baby aura farmer", () => {
  assert.deepEqual(ladderPosition(TIERS, "certified menace", 12_480), {
    index: 2,
    next: { name: "baby aura farmer", distance: 5_021 },
  });
});

test("the top tier has nothing above it", () => {
  assert.deepEqual(ladderPosition(TIERS, "aura farming god", 24_000), { index: 0, next: null });
});

test("the bottom tier counts up from zero", () => {
  assert.deepEqual(ladderPosition(TIERS, "npc arc", 450).next, { name: "side character energy", distance: 1_550 });
});

test("an unknown tier marks no rung", () => {
  assert.deepEqual(ladderPosition(TIERS, "nobody", 100), { index: -1, next: null });
  assert.deepEqual(ladderPosition([], "npc arc", 100), { index: -1, next: null });
});

test("counts of one read in the singular", () => {
  assert.equal(timesLabel(9), "9 times");
  assert.equal(timesLabel(1), "1 time");
  assert.equal(daysLabel(6), "6 days");
  assert.equal(daysLabel(1), "1 day");
  assert.equal(daysLabel(1200), "1,200 days");
});
