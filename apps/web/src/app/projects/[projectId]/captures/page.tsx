import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { AppHeader } from "@/components/app-header";
import { CaptureUploader } from "@/components/capture-uploader";
import { getCaptures, getCurrentUser, getFloors, getProject, getStorageStatus } from "@/lib/server-api";

export const metadata: Metadata = { title: "Captures 360°" };

export default async function CapturesPage({ params }: { params: Promise<{ projectId: string }> }) {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  const { projectId } = await params;
  const [project, floors, captures, storageStatus] = await Promise.all([
    getProject(projectId),
    getFloors(projectId),
    getCaptures(projectId),
    getStorageStatus(projectId),
  ]);

  return (
    <div className="app-frame">
      <AppHeader user={user} />
      <div className="workspace">
        <aside className="sidebar">
          <p className="sidebar-label">{project.name}</p>
          <nav>
            <Link href="/projects">← โครงการทั้งหมด</Link>
            <span>ภาพรวม</span><span>แบบและพื้นที่</span>
            <Link href={`/projects/${projectId}/schedule`}>แผนงานและ Progress</Link>
            <Link className="is-active" href={`/projects/${projectId}/captures`}>Captures</Link>
            <Link href={`/projects/${projectId}/dashboard`}>Dashboard</Link>
            <Link href={`/projects/${projectId}/members`}>สมาชิก</Link>
            <Link href={`/projects/${projectId}/settings`}>ตั้งค่าโครงการ</Link>
          </nav>
        </aside>
        <main className="workspace-main">
          <div className="workspace-heading">
            <div><p className="eyebrow">SITE CAPTURE · SPATIAL RECORD</p><h1>Captures 360°</h1><p>อัปโหลดวิดีโอ 360 จากหน้างานเพื่อสร้างเส้นทางและหลักฐาน Progress</p></div>
          </div>
          <CaptureUploader captures={captures} floors={floors} projectId={projectId} role={project.role} storageStatus={storageStatus} />
        </main>
      </div>
    </div>
  );
}
