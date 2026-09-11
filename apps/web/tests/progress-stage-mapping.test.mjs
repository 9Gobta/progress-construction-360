import assert from "node:assert/strict";
import test from "node:test";

import { beamRangeMatchesBulkRemoval, beamStageForActivity, compareWbs } from "../src/lib/progress-stage-mapping.ts";

const upperFloorStages = [
  { code: "SHORING" },
  { code: "REBAR" },
  { code: "FORMWORK" },
  { code: "CONCRETE" },
  { code: "STRIP_FORM" },
];

test("maps upper-floor beam activities by name instead of source row order", () => {
  assert.equal(beamStageForActivity("งานผูกเหล็กคานชั้น 3", upperFloorStages, 0), "REBAR");
  assert.equal(beamStageForActivity("งานค้ำยันคานชั้น 3", upperFloorStages, 1), "SHORING");
  assert.equal(beamStageForActivity("งานตั้งแบบคานชั้น 3", upperFloorStages, 2), "FORMWORK");
  assert.equal(beamStageForActivity("งานเทคานชั้น 3", upperFloorStages, 3), "CONCRETE");
  assert.equal(beamStageForActivity("งานถอดแบบคานชั้น 3", upperFloorStages, 4), "STRIP_FORM");
});

test("sorts inserted shoring activity before the existing beam stages", () => {
  const rows = ["1.2.3.1.2", "1.2.3.1.1", "1.2.3.1.10"];
  assert.deepEqual(rows.sort(compareWbs), ["1.2.3.1.1", "1.2.3.1.2", "1.2.3.1.10"]);
});

test("removes the corresponding full-length range from every selected beam", () => {
  const selected = { start_m: 0, end_m: 4 };
  assert.equal(beamRangeMatchesBulkRemoval({ start_m: 0, end_m: 4 }, selected, 4, 4), true);
  assert.equal(beamRangeMatchesBulkRemoval({ start_m: 0, end_m: 6 }, selected, 6, 4), true);
  assert.equal(beamRangeMatchesBulkRemoval({ start_m: 1, end_m: 3 }, selected, 6, 4), false);
});

test("removes only an identical partial range from selected beams", () => {
  const selected = { start_m: 1, end_m: 3 };
  assert.equal(beamRangeMatchesBulkRemoval({ start_m: 1, end_m: 3 }, selected, 6, 4), true);
  assert.equal(beamRangeMatchesBulkRemoval({ start_m: 0, end_m: 6 }, selected, 6, 4), false);
  assert.equal(beamRangeMatchesBulkRemoval({ start_m: 1, end_m: 2.5 }, selected, 6, 4), false);
});
