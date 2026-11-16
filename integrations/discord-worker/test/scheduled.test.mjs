// Run with `npm test`. Calls the Worker's real scheduled() with fetch
// stubbed, so no request leaves the machine.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { afterEach, beforeEach, test } from "node:test";
import worker, { DATABASE_CRON, KEEP_AWAKE_CRON } from "../src/index.ts";
import { isWakingHour } from "../src/wakingHours.ts";

const env = { BACKEND_URL: "https://backend.example/" };
const realFetch = globalThis.fetch;
let requested;

beforeEach(() => {
  requested = [];
  globalThis.fetch = async (url) => {
    requested.push(String(url));
    return new Response("{}", { status: 200 });
  };
});

afterEach(() => {
  globalThis.fetch = realFetch;
});

async function fire(cron, iso) {
  const pending = [];
  const ctx = { waitUntil: (p) => pending.push(p), passThroughOnException() {} };
  await worker.scheduled({ cron, scheduledTime: Date.parse(iso), noRetry() {} }, env, ctx);
  await Promise.all(pending);
}

test("wrangler.toml schedules exactly the two crons scheduled() knows", () => {
  const toml = readFileSync(new URL("../wrangler.toml", import.meta.url), "utf8");
  const crons = [...toml.match(/crons = \[(.*)\]/)[1].matchAll(/"([^"]+)"/g)].map((m) => m[1]);
  assert.deepEqual(crons.sort(), [KEEP_AWAKE_CRON, DATABASE_CRON].sort());
});

test("the database cron fires three times a day, every time inside waking hours", () => {
  const [minute, hours, ...rest] = DATABASE_CRON.split(" ");
  assert.equal(minute, "0");
  assert.deepEqual(rest, ["*", "*", "*"]);
  const utcHours = hours.split(",").map(Number);
  assert.deepEqual(utcHours, [13, 17, 21]);
  // Both offsets: every day of the year, each run lands in a waking hour.
  for (let day = 0; day < 366; day++) {
    for (const hour of utcHours) {
      const instant = new Date(Date.UTC(2026, 0, 1 + day, hour));
      assert.ok(isWakingHour(instant), `database ping outside waking hours at ${instant.toISOString()}`);
    }
  }
});

test("the database cron asks for /health/db and nothing else", async () => {
  await fire(DATABASE_CRON, "2026-11-15T17:00:00Z");
  assert.deepEqual(requested, ["https://backend.example/health/db"]);
});

test("the database cron does not depend on the waking-hours check", async () => {
  await fire(DATABASE_CRON, "2026-11-15T08:00:00Z");
  assert.deepEqual(requested, ["https://backend.example/health/db"]);
});

test("the 5-minute cron still asks for /health during waking hours", async () => {
  await fire(KEEP_AWAKE_CRON, "2026-11-15T17:00:00Z");
  assert.deepEqual(requested, ["https://backend.example/health"]);
});

test("the 5-minute cron still stays quiet overnight", async () => {
  await fire(KEEP_AWAKE_CRON, "2026-11-15T08:00:00Z");
  assert.deepEqual(requested, []);
});

test("an unknown cron requests nothing", async () => {
  await fire("0 0 * * *", "2026-11-15T17:00:00Z");
  assert.deepEqual(requested, []);
});

test("a failed database ping is logged, not thrown", async () => {
  globalThis.fetch = async () => {
    throw new Error("network down");
  };
  await fire(DATABASE_CRON, "2026-11-15T17:00:00Z");
});
