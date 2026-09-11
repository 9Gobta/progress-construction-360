import { notFound, redirect } from "next/navigation";

import { AppHeader } from "@/components/app-header";
import { CaptureCompareWorkspace } from "@/components/capture-compare-workspace";
import { ApiError, getCaptureDetail, getCaptures, getCurrentUser, getFloors, getProject } from "@/lib/server-api";

export default async function ComparePage({ params, searchParams }: {
  params: Promise<{ projectId: string }>;
  searchParams: Promise<{ left?: string; right?: string }>;
}) {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  const { projectId } = await params;
  const query = await searchParams;
  const [project, captures, floors] = await Promise.all([getProject(projectId), getCaptures(projectId), getFloors(projectId)]);
  if (!captures.length) notFound();
  const leftId = captures.some((item) => item.id === query.left) ? query.left! : captures[Math.max(0, captures.length - 2)].id;
  const rightId = captures.some((item) => item.id === query.right) ? query.right! : captures[captures.length - 1].id;
  const [left, right] = await Promise.all([getCaptureDetail(projectId, leftId), getCaptureDetail(projectId, rightId)]).catch((error: unknown) => {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  });
  return <div className="app-frame"><AppHeader user={user} viewerTitle={`${project.name} · เปรียบเทียบต่างวัน`} /><main className="compare-page"><CaptureCompareWorkspace captures={captures} floors={floors} left={left} projectId={projectId} right={right} /></main></div>;
}
