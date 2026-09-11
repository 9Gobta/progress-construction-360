import assert from "node:assert/strict";
import test from "node:test";

import { categoryFromIfcType } from "../src/lib/bim-categories.ts";

test("groups structural IFC products into viewer filters", () => {
  assert.equal(categoryFromIfcType("IFCBEAM"), "frame");
  assert.equal(categoryFromIfcType("IfcColumn"), "frame");
  assert.equal(categoryFromIfcType("IFCSLAB"), "slab");
  assert.equal(categoryFromIfcType("IFCSTAIRFLIGHT"), "stair");
  assert.equal(categoryFromIfcType("IFCREINFORCINGBAR"), "rebar");
  assert.equal(categoryFromIfcType("IFCWALL"), "other");
});
