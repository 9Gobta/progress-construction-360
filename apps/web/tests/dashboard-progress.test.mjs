import assert from "node:assert/strict";
import test from "node:test";

import { bangkokDateKey, latestProgressAt } from "../src/lib/dashboard-progress.ts";

test("groups late-night UTC observations by Bangkok calendar date", () => {
  assert.equal(bangkokDateKey("2026-07-02T18:30:00.000Z"), "2026-07-03");
});

test("selects the newest observation even when API rows are unordered", () => {
  const entries = [
    { activity_id: "beam", observed_at: "2026-07-01T10:00:00Z", created_at: "2026-07-01T10:01:00Z", progress_percent: 40 },
    { activity_id: "beam", observed_at: "2026-06-30T10:00:00Z", created_at: "2026-07-02T10:01:00Z", progress_percent: 20 },
    { activity_id: "beam", observed_at: "2026-07-03T10:00:00Z", created_at: "2026-07-03T10:01:00Z", progress_percent: 80 },
  ];
  const latest = latestProgressAt(entries, Date.parse("2026-07-02T23:59:59Z"), (entry) => entry.activity_id);
  assert.equal(latest.get("beam")?.progress_percent, 40);
});

test("uses creation time to break ties between corrections on the same observation date", () => {
  const entries = [
    { activity_id: "column", observed_at: "2026-07-03T10:00:00Z", created_at: "2026-07-03T10:01:00Z", progress_percent: 50 },
    { activity_id: "column", observed_at: "2026-07-03T10:00:00Z", created_at: "2026-07-03T10:05:00Z", progress_percent: 75 },
  ];
  const latest = latestProgressAt(entries, Date.parse("2026-07-03T23:59:59Z"), (entry) => entry.activity_id);
  assert.equal(latest.get("column")?.progress_percent, 75);
});
