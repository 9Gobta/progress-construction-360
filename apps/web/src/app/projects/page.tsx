import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { AppHeader } from "@/components/app-header";
import { CreateProjectForm } from "@/components/create-project-form";
import { getCurrentUser, getProjects } from "@/lib/server-api";

export const metadata: Metadata = { title: "โครงการ" };

export default async function ProjectsPage() {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  const projects = await getProjects();

  return (
    <div className="app-frame">
      <AppHeader user={user} />
      <div className="workspace">
        <aside className="sidebar">
          <p className="sidebar-label">WORKSPACE</p>
          <nav>
            <Link className="is-active" href="/projects">โครงการ</Link>
            <span>แบบและพื้นที่</span><span>Schedule</span><span>Capture</span>
            <span>ตรวจ Progress</span><span>Dashboard</span><span>Reports</span>
          </nav>
        </aside>
        <main className="workspace-main">
          <div className="workspace-heading">
            <div>
              <h1>โครงการของคุณ</h1>
              <p>เลือกโครงการเดิมหรือสร้างโครงการทดลองสำหรับอาคารหอพัก</p>
            </div>
          </div>
          <div className="content-grid">
            <section className="panel">
              <div className="panel-header"><h2>โครงการทั้งหมด</h2><span>{projects.length} โครงการ</span></div>
              {projects.length ? (
                <div className="project-list">
                  {projects.map((project) => (
                    <Link className="project-row" href={`/projects/${project.id}/schedule`} key={project.id}>
                      <div>
                        <h3>{project.name}</h3>
                        <p>{project.location || "ยังไม่ระบุที่ตั้ง"} · {project.timezone}</p>
                      </div>
                      <span className="role-badge">{project.role}</span>
                      <span>{new Intl.DateTimeFormat("th-TH", { dateStyle: "medium" }).format(new Date(project.updated_at))}</span>
                    </Link>
                  ))}
                </div>
              ) : (
                <div className="empty-state"><strong>ยังไม่มีโครงการ</strong><p>สร้างโครงการแรกจากแบบฟอร์มด้านข้าง</p></div>
              )}
            </section>
            <aside className="panel create-panel">
              <h2>สร้างโครงการใหม่</h2>
              <p>เริ่มจากข้อมูลหลักก่อน รายชื่อห้องและรายละเอียดอื่นเพิ่มภายหลังได้</p>
              <CreateProjectForm />
            </aside>
          </div>
        </main>
      </div>
    </div>
  );
}
