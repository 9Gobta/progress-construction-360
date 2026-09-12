import Link from "next/link";
import { redirect } from "next/navigation";

import { AppHeader } from "@/components/app-header";
import { DailyReportWorkspace } from "@/components/daily-report-workspace";
import { getCaptureDetail, getCaptures, getCurrentUser, getFieldNotes, getProgressComparison, getProject, getSchedules } from "@/lib/server-api";

export default async function DailyReportPage({ params, searchParams }: {
  params: Promise<{ projectId: string }>;
  searchParams: Promise<{ captureId?: string }>;
}) {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  const { projectId } = await params;
  const query = await searchParams;
  const [project, captures, schedules] = await Promise.all([
    getProject(projectId), getCaptures(projectId), getSchedules(projectId),
  ]);
  const ordered = [...captures].sort((a, b) => b.captured_at.localeCompare(a.captured_at));
  const selected = ordered.find((item) => item.id === query.captureId) ?? ordered[0] ?? null;
  if (!selected) return <div className="app-frame"><AppHeader user={user} /><div className="workspace"><aside className="sidebar"><p className="sidebar-label">{project.name}</p><nav><Link href={`/projects/${projectId}/captures`}>← Captures 360°</Link></nav></aside><main className="workspace-main"><div className="empty-state"><strong>ยังไม่มี Capture สำหรับสร้างรายงาน</strong><p>อัปโหลดข้อมูลสำรวจ 360 ก่อน แล้วระบบจะสร้างรายงานประจำวันให้โดยอัตโนมัติ</p><Link className="button button-primary" href={`/projects/${projectId}/captures`}>ไปหน้า Captures</Link></div></main></div></div>;
  const previous = ordered[ordered.findIndex((item) => item.id === selected.id) + 1] ?? null;
  const hasSchedule = schedules.some((item) => item.status === "READY");
  const [detail, notes, comparison, previousComparison] = await Promise.all([
    getCaptureDetail(projectId, selected.id),
    getFieldNotes(projectId, `capture_id=${encodeURIComponent(selected.id)}`).catch(() => []),
    hasSchedule ? getProgressComparison(projectId, selected.id).catch(() => null) : Promise.resolve(null),
    hasSchedule && previous ? getProgressComparison(projectId, previous.id).catch(() => null) : Promise.resolve(null),
  ]);
  return <div className="app-frame"><AppHeader user={user} /><div className="workspace daily-report-workspace-shell">
    <aside className="sidebar daily-report-sidebar"><p className="sidebar-label">{project.name}</p><nav>
      <Link href="/projects">← โครงการทั้งหมด</Link><Link href={`/projects/${projectId}/schedule`}>แผนงานและ Progress</Link><Link href={`/projects/${projectId}/captures`}>Captures 360°</Link><Link href={`/projects/${projectId}/dashboard`}>Dashboard</Link><Link className="is-active" href={`/projects/${projectId}/reports/daily`}>รายงานประจำวัน</Link><Link href={`/projects/${projectId}/field-notes`}>ประเด็นหน้างาน</Link><Link href={`/projects/${projectId}/settings`}>ตั้งค่าโครงการ</Link>
    </nav></aside>
    <main className="workspace-main"><DailyReportWorkspace captures={captures} comparison={comparison} detail={detail} notes={notes} previousComparison={previousComparison} project={project} /></main>
  </div></div>;
}
