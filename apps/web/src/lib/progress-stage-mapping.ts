export type BeamStageCode = "SETTING_OUT" | "SHORING" | "REBAR" | "FORMWORK" | "CONCRETE" | "STRIP_FORM";
export type BeamProgressRange = { start_m: number; end_m: number };

export function beamRangeMatchesBulkRemoval(
  range: BeamProgressRange,
  selectedRange: BeamProgressRange,
  itemLength: number,
  primaryLength: number,
) {
  const tolerance = 1e-6;
  const selectedCoversWholePrimary = Math.abs(selectedRange.start_m) < tolerance
    && Math.abs(selectedRange.end_m - primaryLength) < tolerance;
  if (selectedCoversWholePrimary) {
    return Math.abs(range.start_m) < tolerance
      && Math.abs(range.end_m - itemLength) < tolerance;
  }
  return Math.abs(range.start_m - selectedRange.start_m) < tolerance
    && Math.abs(range.end_m - selectedRange.end_m) < tolerance;
}

export function compareWbs(left: string, right: string) {
  return left.localeCompare(right, undefined, { numeric: true });
}

export function beamStageThreshold(activityName: string, fallbackIndex: number, fallbackTotal: number) {
  if (activityName.includes("ค้ำยัน") || activityName.includes("ตีเส้น") || activityName.includes("เตรียมแนว")) return 20;
  if (activityName.includes("ผูกเหล็ก")) return 40;
  if (activityName.includes("เข้าแบบ") || activityName.includes("ตั้งแบบ")) return 60;
  if (activityName.includes("เท")) return 80;
  if (activityName.includes("ถอดแบบ") || activityName.includes("แกะแบบ")) return 100;
  return ((fallbackIndex + 1) * 100) / Math.max(fallbackTotal, 1);
}

export function beamStageForActivity(
  activityName: string,
  stages: ReadonlyArray<{ code: BeamStageCode }>,
  fallbackIndex: number,
): BeamStageCode {
  if (activityName.includes("ค้ำยัน")) return "SHORING";
  if (
    activityName.includes("ตีเส้น")
    || activityName.includes("เตรียมแนว")
    || activityName.includes("กำหนดแนว")
  ) return "SETTING_OUT";
  if (activityName.includes("ผูกเหล็ก")) return "REBAR";
  if (activityName.includes("เข้าแบบ") || activityName.includes("ตั้งแบบ")) return "FORMWORK";
  if (activityName.includes("เท")) return "CONCRETE";
  if (activityName.includes("ถอดแบบ") || activityName.includes("แกะแบบ")) return "STRIP_FORM";
  return stages[Math.min(Math.max(fallbackIndex, 0), stages.length - 1)]?.code ?? stages[0]?.code ?? "SETTING_OUT";
}
