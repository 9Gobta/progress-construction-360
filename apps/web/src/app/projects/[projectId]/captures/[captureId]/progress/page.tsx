import { redirect } from "next/navigation";

import { AppHeader } from "@/components/app-header";
import { ViewerIconRail } from "@/components/viewer-icon-rail";
import { WorkProgressWorkspace } from "@/components/work-progress-workspace";
import {
  getCaptureDetail,
  getCurrentUser,
  getFloors,
  getProject,
  getWorkProgress,
} from "@/lib/server-api";

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
  const [project, detail, floors] = await Promise.all([
    getProject(projectId),
    getCaptureDetail(projectId, captureId),
    getFloors(projectId),
  ]);
  const captureDate = detail.capture.captured_at.slice(0, 10);
  const availableFloors = floors.filter((floor) => (
    !floor.available_from || floor.available_from <= captureDate
  ));
  const requestedFloorId = (await searchParams).floorId;
  const floorId = availableFloors.some((floor) => floor.id === requestedFloorId)
    ? requestedFloorId!
    : detail.capture.start_floor_id;
  const progress = await getWorkProgress(projectId, captureId, floorId);

  return (
    <div className="app-frame">
      <AppHeader user={user} viewerTitle={`${project.name} · ตรวจ Progress`} />
      <div className="workspace viewer-workspace">
        <ViewerIconRail captureId={captureId} projectId={projectId} />
        <main className="workspace-main beam-progress-page">
          <div className="workspace-heading">
            <div>
              <p className="eyebrow">HUMAN STRUCTURAL INSPECTION</p>
              <h1>ตรวจ Progress งานโครงสร้าง</h1>
              <p>
                ผู้ตรวจประเมินจากภาพ 360° พร้อมเลือกภาพหลักฐาน ระบบบันทึกผลแยกตามบัญชีผู้ใช้งาน
              </p>
            </div>
          </div>
          <WorkProgressWorkspace
            canEdit={project.role === "admin" || project.role === "sub_admin" || project.role === "reviewer"}
            captureId={captureId}
            detail={detail}
            floorId={floorId}
            floors={availableFloors}
            progress={progress}
            projectId={projectId}
          />
        </main>
      </div>
    </div>
  );
}
