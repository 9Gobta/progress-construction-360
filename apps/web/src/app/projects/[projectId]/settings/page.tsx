import Link from "next/link";
import { redirect } from "next/navigation";

import { AppHeader } from "@/components/app-header";
import { ProjectSettingsWorkspace } from "@/components/project-settings-workspace";
import { getBimModels, getCurrentUser, getFloors, getProject } from "@/lib/server-api";

export default async function ProjectSettingsPage({ params }: { params: Promise<{ projectId: string }> }) {
  const user = await getCurrentUser(); if (!user) redirect("/login");
  const { projectId } = await params;
  const [project, floors, bimModels] = await Promise.all([getProject(projectId), getFloors(projectId), getBimModels(projectId).catch(() => ({ active: null, versions: [] }))]);
  return <div className="app-frame"><AppHeader user={user} /><div className="workspace"><aside className="sidebar"><p className="sidebar-label">{project.name}</p><nav><Link href="/projects">← โครงการทั้งหมด</Link><Link className="is-active" href={`/projects/${projectId}/settings`}>ตั้งค่าโครงการ</Link><Link href={`/projects/${projectId}/schedule`}>แผนงานและ Progress</Link><Link href={`/projects/${projectId}/captures`}>Captures 360°</Link><Link href={`/projects/${projectId}/dashboard`}>Dashboard</Link><Link href={`/projects/${projectId}/members`}>สมาชิก</Link></nav></aside><main className="workspace-main"><div className="workspace-heading"><div><p className="eyebrow">PROJECT SETUP</p><h1>ตั้งค่าโครงการ</h1><p>เตรียมรายละเอียด แปลน BIM แผนงาน และทีม ก่อนเริ่ม Capture</p></div></div><ProjectSettingsWorkspace bimModels={bimModels} floors={floors} project={project} /></main></div></div>;
}
