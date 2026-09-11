import assert from "node:assert/strict";
import test from "node:test";

import {
  fitPlanToIfc,
  planDirectionInThree,
  transformPlanPoint,
  validatePlanToIfcOrientation,
} from "../src/lib/bim-registration.ts";

const projectTransform = {
  coefficientsX: [14.973, -27.772, -9.659],
  coefficientsY: [39.005, 10.661, -5.224],
};

test("fits the reviewed plan-to-IFC registration without mirroring", () => {
  const planPoints = [[0.2, 0.27], [0.65, 0.27], [0.2, 0.61], [0.65, 0.61]];
  const pairs = planPoints.map((plan) => ({
    plan,
    ifc: transformPlanPoint(projectTransform, ...plan),
  }));
  const fitted = fitPlanToIfc(pairs);
  assert.ok(fitted);
  assert.equal(validatePlanToIfcOrientation(fitted).valid, true);
  const actual = transformPlanPoint(fitted, 0.43, 0.51);
  const expected = transformPlanPoint(projectTransform, 0.43, 0.51);
  assert.ok(Math.hypot(actual[0] - expected[0], actual[1] - expected[1]) < 1e-8);
});

test("rejects a low-error but mirrored registration", () => {
  const mirrored = {
    coefficientsX: [-14.973, -27.772, -9.659],
    coefficientsY: [-39.005, 10.661, -5.224],
  };
  assert.ok(validatePlanToIfcOrientation(mirrored).determinant < 0);
  assert.equal(validatePlanToIfcOrientation(mirrored).valid, false);
});

test("maps panorama turns through the plan transform in the correct direction", () => {
  const forward = planDirectionInThree(projectTransform, 0);
  const right = planDirectionInThree(projectTransform, 90);
  assert.ok(forward && right);
  assert.ok(Math.abs(forward[0] * right[0] + forward[2] * right[2]) < 1e-4);
  assert.ok(forward[0] * right[2] - forward[2] * right[0] < 0);
});
