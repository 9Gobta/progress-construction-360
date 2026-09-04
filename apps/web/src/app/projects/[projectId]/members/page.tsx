import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { AppHeader } from "@/components/app-header";
import { ProjectMembersManager } from "@/components/project-members-manager";
import { getCurrentUser, getProject, getProjectMembers } from "@/lib/server-api";

export const metadata: Metadata = { title: "สมาชิกโครงการ" };

export default async function ProjectMembersPage({ params }: { params: Promise<{ projectId: string }> }) {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  const { projectId } = await params;
  const [project, members] = await Promise.all([getProject(projectId), getProjectMembers(projectId)]);

  return (
    <div className="app-frame">
      <AppHeader user={user} />
      <div className="workspace">
        <aside className="sidebar">
          <p className="sidebar-label">{project.name}</p>
          <nav>
            <Link href="/projects">← โครงการทั้งหมด</Link>
            <Link href={`/projects/${projectId}/schedule`}>แผนงานและ Progress</Link>
            <Link href={`/projects/${projectId}/captures`}>Captures 360°</Link>
            <Link href={`/projects/${projectId}/dashboard`}>Dashboard</Link>
            <Link className="is-active" href={`/projects/${projectId}/members`}>สมาชิก</Link>
            <Link href={`/projects/${projectId}/settings`}>ตั้งค่าโครงการ</Link>
          </nav>
        </aside>
        <main className="workspace-main members-page">
          <div className="workspace-heading">
            <div><p className="eyebrow">PROJECT TEAM</p><h1>สมาชิกและสิทธิ์</h1><p>เชิญเพื่อนในกลุ่มเข้าดูภาพ 360° และช่วยกรอก Progress งานโครงสร้าง</p></div>
          </div>
          <ProjectMembersManager projectId={projectId} initialMembers={members} currentUserId={user.id} canManage={project.role === "admin"} />
        </main>
      </div>
    </div>
  );
}
