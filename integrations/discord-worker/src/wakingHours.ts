/**
 * The hours the keep-awake ping runs: 8 AM to midnight in New York.
 *
 * Cron Triggers only understand UTC, and New York is four hours behind UTC
 * in summer and five in winter. So wrangler.toml schedules every UTC hour
 * that is a waking hour under either offset, and each run asks this
 * whether it is one right now. Nothing needs editing when the clocks
 * change.
 */

const FIRST_WAKING_HOUR = 8;

const newYorkHour = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York",
  hour: "numeric",
  hourCycle: "h23",
});

export function isWakingHour(at: Date): boolean {
  return Number(newYorkHour.format(at)) >= FIRST_WAKING_HOUR;
}
