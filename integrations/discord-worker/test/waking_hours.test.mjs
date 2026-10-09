// Run with `npm test`. Node strips the types from the .ts import itself.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { isWakingHour } from "../src/wakingHours.ts";

const at = (iso) => new Date(iso);

test("summer: 8 AM to midnight Eastern is 12:00 to 04:00 UTC", () => {
  assert.equal(isWakingHour(at("2026-10-09T11:55:00Z")), false);
  assert.equal(isWakingHour(at("2026-10-09T12:00:00Z")), true);
  assert.equal(isWakingHour(at("2026-10-10T03:55:00Z")), true);
  assert.equal(isWakingHour(at("2026-10-10T04:00:00Z")), false);
});

test("winter: the same window is 13:00 to 05:00 UTC", () => {
  assert.equal(isWakingHour(at("2026-11-02T12:55:00Z")), false);
  assert.equal(isWakingHour(at("2026-11-02T13:00:00Z")), true);
  assert.equal(isWakingHour(at("2026-11-03T04:55:00Z")), true);
  assert.equal(isWakingHour(at("2026-11-03T05:00:00Z")), false);
});

test("the night the clocks go back (2026-11-01) and forward (2027-03-14)", () => {
  // 1 AM happens twice on 2026-11-01. Both are before 8 AM.
  assert.equal(isWakingHour(at("2026-11-01T05:30:00Z")), false);
  assert.equal(isWakingHour(at("2026-11-01T06:30:00Z")), false);
  assert.equal(isWakingHour(at("2026-11-01T12:30:00Z")), false);
  assert.equal(isWakingHour(at("2026-11-01T13:00:00Z")), true);
  assert.equal(isWakingHour(at("2027-03-14T11:55:00Z")), false);
  assert.equal(isWakingHour(at("2027-03-14T12:00:00Z")), true);
});

test("the cron schedule fires in every waking hour of the year", () => {
  const toml = readFileSync(new URL("../wrangler.toml", import.meta.url), "utf8");
  const [, minutes, hours] = toml.match(/crons = \["(\S+) (\S+) \* \* \*"\]/);
  assert.equal(minutes, "*/5");
  const scheduled = new Set(
    hours.split(",").flatMap((part) => {
      const [from, to = from] = part.split("-").map(Number);
      return Array.from({ length: to - from + 1 }, (_, i) => from + i);
    }),
  );
  const start = Date.UTC(2026, 0, 1);
  for (let hour = 0; hour < 366 * 24; hour++) {
    const instant = new Date(start + hour * 3_600_000);
    if (isWakingHour(instant)) {
      assert.ok(scheduled.has(instant.getUTCHours()), `no run scheduled at ${instant.toISOString()}`);
    }
  }
});
