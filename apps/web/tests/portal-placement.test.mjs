import assert from "node:assert/strict";
import test from "node:test";

import { groundPortalPlacement } from "../src/lib/portal-placement.ts";

test("calibrates a floor portal from reconstructed camera height", () => {
  const placement = groundPortalPlacement({
    distance: 1.65,
    localYawDeg: 0,
    reconstructedCameraHeight: 1.65,
    fallbackStep: 0.2,
  });

  assert.equal(placement.horizontalDistance, 180);
  assert.equal(placement.x, -180);
  assert.equal(placement.y, -180);
  assert.ok(Math.abs(placement.z) < 1e-8);
  assert.equal(placement.pitchDeg, -45);
});

test("keeps the hotspot on the floor despite reconstructed vertical drift", () => {
  const placement = groundPortalPlacement({
    distance: 3.3,
    localYawDeg: 90,
    reconstructedCameraHeight: 1.65,
    fallbackStep: 0.2,
  });

  assert.equal(placement.y, -180);
  assert.ok(Math.abs(placement.x) < 1e-8);
  assert.equal(placement.z, -360);
  assert.ok(placement.pitchDeg < 0);
});

test("falls back to the local walking cadence for a legacy trajectory", () => {
  const placement = groundPortalPlacement({
    distance: 0.2,
    localYawDeg: 0,
    reconstructedCameraHeight: null,
    fallbackStep: 0.2,
  });

  assert.equal(placement.horizontalDistance, 36);
  assert.equal(placement.y, -180);
});
