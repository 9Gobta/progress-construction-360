import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { AppHeader } from "@/components/app-header";
import { ScheduleWorkspace } from "@/components/schedule-workspace";
import { getActivities, getCurrentUser, getHumanProgress, getProject, getSchedules } from "@/lib/server-api";

export const metadata: Metadata = { title: "แผนงานและความก้าวหน้า" };

export default async function SchedulePage({ params }: { params: Promise<{ projectId: string }> }) {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  const { projectId } = await params;
  const [project, schedules, progress] = await Promise.all([
    getProject(projectId),
    getSchedules(projectId),
    getHumanProgress(projectId),
  ]);
  const selectedSchedule = schedules.find((item) => item.is_baseline) ?? schedules[0];
  const activities = selectedSchedule ? await getActivities(projectId, selectedSchedule.id) : [];

  return (
    <div className="app-frame">
      <AppHeader user={user} />
      <div className="workspace">
        <aside className="sidebar">
          <p className="sidebar-label">{project.name}</p>
          <nav>
            <Link href="/projects">← โครงการทั้งหมด</Link>
            <Link className="is-active" href={`/projects/${projectId}/schedule`}>แผนงานและ Progress</Link>
            <Link href={`/projects/${projectId}/captures`}>Captures</Link><Link href={`/projects/${projectId}/dashboard`}>Dashboard</Link><Link href={`/projects/${projectId}/members`}>สมาชิก</Link><Link href={`/projects/${projectId}/settings`}>ตั้งค่าโครงการ</Link>
          </nav>
        </aside>
        <main className="workspace-main">
          <div className="workspace-heading">
            <div><p className="eyebrow">WEEK 2 · SCHEDULE FOUNDATION</p><h1>แผนงานและ Progress</h1><p>Excel เป็น Planned Schedule ส่วนความก้าวหน้าจริงให้คนกรอกบนเว็บ</p></div>
            {selectedSchedule && <div className="version-chip"><span>ใช้งานอยู่</span><strong>{selectedSchedule.name}</strong><small>{selectedSchedule.row_count} กิจกรรม · Version {selectedSchedule.version_no}</small></div>}
          </div>
          <ScheduleWorkspace activities={activities} progress={progress} projectId={projectId} role={project.role} />
        </main>
      </div>
    </div>
  );
}
