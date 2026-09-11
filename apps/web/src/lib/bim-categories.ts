export type BimCategoryKey = "frame" | "slab" | "stair" | "rebar" | "other";

export function categoryFromIfcType(typeName: string): BimCategoryKey {
  const normalized = typeName.toUpperCase();
  if (/IFC(REINFORCING|TENDON)/.test(normalized)) return "rebar";
  if (/IFC(STAIR|RAMP)/.test(normalized)) return "stair";
  if (/IFC(SLAB|ROOF)/.test(normalized)) return "slab";
  if (/IFC(BEAM|COLUMN|FOOTING|PILE|MEMBER|PLATE)/.test(normalized)) return "frame";
  return "other";
}
