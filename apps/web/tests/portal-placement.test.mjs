import assert from "node:assert/strict";
import test from "node:test";

import {
  groundPortalPlacement,
  portalArrivalViewLongitude,
} from "../src/lib/portal-placement.ts";

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
  assert.equal(placement.radius, 16);
});

test("keeps a nearby portal large enough to see and select", () => {
  const placement = groundPortalPlacement({
    distance: 0.01,
    localYawDeg: 0,
    reconstructedCameraHeight: null,
    fallbackStep: 1,
  });

  assert.equal(placement.radius, 1.25);
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

test("uses the reconstructed camera ray for a pitched panorama", () => {
  const placement = groundPortalPlacement({
    distance: 1.65,
    localYawDeg: 0,
    localPitchDeg: -30,
    reconstructedCameraHeight: 1.65,
    fallbackStep: 0.2,
  });

  assert.equal(placement.pitchDeg, -30);
  assert.ok(Math.abs(placement.y - Math.tan(-Math.PI / 6) * 180) < 1e-8);
});

test("keeps a noisy same-floor portal below the panorama horizon", () => {
  const placement = groundPortalPlacement({
    distance: 1.65,
    localYawDeg: 0,
    localPitchDeg: 8,
    reconstructedCameraHeight: 1.65,
    fallbackStep: 0.2,
  });

  assert.equal(placement.pitchDeg, -2);
  assert.ok(placement.y < 0);
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

test("arrives facing exactly away from the reciprocal station", () => {
  const targetReturnPortalYaw = 11;
  const targetLongitude = portalArrivalViewLongitude({
    targetReturnPortalYaw,
  });

  assert.equal(targetLongitude, -169);
});

test("does not accumulate an off-centre click across later warps", () => {
  const targetReturnPortalYaw = -131;
  const targetLongitude = portalArrivalViewLongitude({
    targetReturnPortalYaw,
  });

  assert.equal(targetLongitude, 49);
});
