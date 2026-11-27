// Run by `npm test` and by prebuild: node --test, no test framework.
import { test } from "node:test";
import assert from "node:assert/strict";
import { templateLabel } from "./templateLabel.ts";

test("the all-caps opening line is the label", () => {
  assert.equal(templateLabel("SETTLED PREFERENCE: A verdict already reached — smugly reject"), "SETTLED PREFERENCE");
});

test("brackets, quotes, hyphens and commas stay in the label", () => {
  assert.equal(templateLabel("PEAK [THING], SERIOUSLY OR IRONICALLY: Declaring"), "PEAK [THING], SERIOUSLY OR IRONICALLY");
  assert.equal(templateLabel("IRONIC 'IT ALWAYS WAS': The reveal"), "IRONIC 'IT ALWAYS WAS'");
  assert.equal(templateLabel("STRONG-THEN VS WEAK-NOW: Third-person"), "STRONG-THEN VS WEAK-NOW");
});

test("a description with no label gives none", () => {
  assert.equal(templateLabel("A dog calmly sipping coffee while the room burns."), null);
  assert.equal(templateLabel("Use when: someone is caught"), null);
  assert.equal(templateLabel(""), null);
});
