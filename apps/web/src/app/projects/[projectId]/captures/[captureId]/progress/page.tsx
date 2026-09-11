import { redirect } from "next/navigation";

import { getCurrentUser } from "@/lib/server-api";

export default async function WorkProgressPage({
  params,
  searchParams,
}: {
  params: Promise<{ projectId: string; captureId: string }>;
  searchParams: Promise<{ floorId?: string }>;
}) {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  const { projectId, captureId } = await params;
  const { floorId } = await searchParams;
  const next = new URLSearchParams({ mode: "track" });
  if (floorId) next.set("floorId", floorId);
  redirect(`/projects/${projectId}/captures/${captureId}?${next.toString()}`);
}
