export function timestamp(value: string) {
  const parsed = new Date(value).getTime();
  return Number.isFinite(parsed) ? parsed : 0;
}

export function bangkokDateKey(value: string) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Bangkok",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(value));
}

type ProgressTimestamp = {
  observed_at: string;
  created_at?: string;
};

/**
 * Returns the newest observation per current activity without relying on API
 * row order. Historical imports can point at an activity from an older
 * schedule, so the caller resolves each row to the current activity id.
 */
export function latestProgressAt<T extends ProgressTimestamp>(
  entries: readonly T[],
  cutoff: number,
  resolveActivityId: (entry: T) => string | undefined,
) {
  const latest = new Map<string, T>();
  const ordered = [...entries].sort((left, right) => {
    const observedDifference = timestamp(right.observed_at) - timestamp(left.observed_at);
    if (observedDifference !== 0) return observedDifference;
    return timestamp(right.created_at ?? right.observed_at) - timestamp(left.created_at ?? left.observed_at);
  });
  for (const entry of ordered) {
    if (timestamp(entry.observed_at) > cutoff) continue;
    const activityId = resolveActivityId(entry);
    if (activityId && !latest.has(activityId)) latest.set(activityId, entry);
  }
  return latest;
}
