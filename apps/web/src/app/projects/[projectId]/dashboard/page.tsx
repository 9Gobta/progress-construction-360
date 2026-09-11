import Link from "next/link";
import { redirect } from "next/navigation";

import { AppHeader } from "@/components/app-header";
import { ProgressTrackDashboard } from "@/components/progress-track-dashboard";
import { getActivities, getCaptures, getCurrentUser, getFloors, getHumanProgress, getProgressComparison, getProject, getSchedules, getStructuralElements } from "@/lib/server-api";

export default async function DashboardPage({ params, searchParams }: { params: Promise<{ projectId: string }>; searchParams: Promise<{ captureId?: string }> }) {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  const { projectId } = await params;
  const query = await searchParams;
  const [project, captures, floors, schedules, progress] = await Promise.all([
    getProject(projectId), getCaptures(projectId), getFloors(projectId), getSchedules(projectId), getHumanProgress(projectId),
  ]);
  const schedule = schedules.find((item) => item.is_baseline && item.status === "READY")
    ?? schedules.find((item) => item.status === "READY") ?? null;
  const activities = schedule ? await getActivities(projectId, schedule.id) : [];
  const structuralElements = (await Promise.all(
    floors.map((floor) => getStructuralElements(projectId, floor.id).catch(() => [])),
  )).flat();
  const requestedCaptureId = query.captureId;
  const captureId = captures.some((item) => item.id === requestedCaptureId)
    ? requestedCaptureId!
    : captures[0]?.id ?? null;
  const comparison = schedule && captureId
    ? await getProgressComparison(projectId, captureId)
    : null;

  return <div className="app-frame"><AppHeader user={user} /><div className="workspace">
    <aside className="sidebar"><p className="sidebar-label">{project.name}</p><nav>
      <Link href="/projects">← โครงการทั้งหมด</Link><Link href={`/projects/${projectId}/schedule`}>แผนงานและ Progress</Link>
      <Link href={`/projects/${projectId}/captures`}>Captures 360°</Link><Link className="is-active" href={`/projects/${projectId}/dashboard`}>Dashboard</Link>
      <Link href={`/projects/${projectId}/members`}>สมาชิก</Link><Link href={`/projects/${projectId}/settings`}>ตั้งค่าโครงการ</Link>
    </nav></aside>
    <main className="workspace-main">
      <div className="workspace-heading"><div><p className="eyebrow">HUMAN PROGRESS TRACKING</p><h1>ติดตาม Progress งานโครงสร้าง</h1><p>ภาพรวมทุกชั้น งานคงเหลือ หลักฐานภาพ 360 และ Productivity เทียบแผน</p></div>
        {schedule && <div className="version-chip"><span>แผนที่ใช้งาน</span><strong>{schedule.name}</strong><small>{schedule.row_count} กิจกรรม · Version {schedule.version_no}</small></div>}
      </div>
      {schedule ? <ProgressTrackDashboard key={captureId} activities={activities} captures={captures} comparison={comparison} floors={floors} initialCaptureId={captureId} progress={progress} projectId={projectId} structuralElements={structuralElements} /> : <div className="empty-state"><strong>ยังไม่มีแผนงานที่พร้อมใช้</strong><p>นำเข้า Excel ในหน้าแผนงานก่อนเปิด Dashboard</p></div>}
    </main>
  </div></div>;
}
