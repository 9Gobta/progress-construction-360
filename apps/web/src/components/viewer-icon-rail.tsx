import Link from "next/link";

function RailIcon({ name }: { name: "projects" | "capture" | "compare" | "notes" | "plan" | "review" | "dashboard" | "report" }) {
  const paths = {
    projects: <><path d="M4 20V7l8-4 8 4v13" /><path d="M8 10h2M14 10h2M8 14h2M14 14h2M10 20v-3h4v3" /></>,
    capture: <><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3c3 3 4 6 4 9s-1 6-4 9c-3-3-4-6-4-9s1-6 4-9Z" /></>,
    compare: <><rect x="3" y="4" width="8" height="16" rx="1" /><rect x="13" y="4" width="8" height="16" rx="1" /><path d="M7 8v8M17 8v8" /></>,
    notes: <><path d="M5 3h14v14H9l-4 4Z" /><path d="M8 7h8M8 11h6" /></>,
    plan: <><path d="m4 6 5-2 6 2 5-2v14l-5 2-6-2-5 2Z" /><path d="M9 4v14M15 6v14" /></>,
    review: <><path d="M7 3h10v4H7zM5 5H3v16h18V5h-2" /><path d="m8 14 3 3 6-7" /></>,
    dashboard: <><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" /></>,
    report: <><path d="M6 3h9l3 3v15H6Z" /><path d="M14 3v4h4M9 11h6M9 15h6M9 18h4" /></>,
  };
  return <svg aria-hidden="true" viewBox="0 0 24 24">{paths[name]}</svg>;
}

export function ViewerIconRail({ projectId, captureId }: { projectId: string; captureId: string }) {
  return <aside className="viewer-icon-rail"><nav aria-label="เครื่องมือโครงการ">
    <Link aria-label="โครงการทั้งหมด" href="/projects" title="โครงการทั้งหมด"><RailIcon name="projects" /></Link>
    <Link aria-label="ภาพ 360" className="is-active" href={`/projects/${projectId}/captures/${captureId}`} title="ภาพ 360"><RailIcon name="capture" /></Link>
    <Link aria-label="เปรียบเทียบต่างวัน" href={`/projects/${projectId}/compare?left=${captureId}`} title="เปรียบเทียบภาพ 360 ต่างวัน"><RailIcon name="compare" /></Link>
    <Link aria-label="ประเด็นหน้างาน" href={`/projects/${projectId}/field-notes`} title="ประเด็นหน้างาน"><RailIcon name="notes" /></Link>
    <Link aria-label="แผนงานและความก้าวหน้า" href={`/projects/${projectId}/schedule`} title="แผนงานและความก้าวหน้า"><RailIcon name="plan" /></Link>
    <Link aria-label="ตรวจ Progress งานโครงสร้าง" href={`/projects/${projectId}/captures/${captureId}?mode=track`} title="ตรวจ Progress งานโครงสร้างใน Viewer"><RailIcon name="review" /></Link>
    <Link aria-label="Dashboard" href={`/projects/${projectId}/dashboard?captureId=${captureId}`} title="Dashboard"><RailIcon name="dashboard" /></Link>
    <Link aria-label="รายงานประจำวัน" href={`/projects/${projectId}/reports/daily?captureId=${captureId}`} title="รายงานประจำวัน"><RailIcon name="report" /></Link>
  </nav></aside>;
}
