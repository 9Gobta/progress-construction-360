import { redirect } from "next/navigation";

import { AppHeader } from "@/components/app-header";
import { CaptureReviewWorkspace } from "@/components/capture-review-workspace";
import { JobStatus } from "@/components/job-status";
import { StitchedVideoUploader } from "@/components/stitched-video-uploader";
import { ViewerIconRail } from "@/components/viewer-icon-rail";
import { ViewerCaptureNavigator } from "@/components/viewer-capture-navigator";
import type { ProcessingJob } from "@/lib/types";
import { getActivities, getBeamProgress, getBimModels, getCaptureDetail, getCaptures, getColumnProgress, getCurrentUser, getFloors, getHumanProgress, getProject, getSchedules, getSlabProgress, getStructuralElements } from "@/lib/server-api";

function EmptyCaptureState({ captureStatus, job, projectId, captureId, canUpload }: {
  captureStatus: string;
  job: ProcessingJob | undefined;
  projectId: string;
  captureId: string;
  canUpload: boolean;
}) {
  const needsStitcher = captureStatus === "STITCHER_REQUIRED" || job?.error_code === "Insta360StitcherUnavailable";
  const failed = job?.status === "FAILED";

  if (needsStitcher) {
    return (
      <section className="capture-processing-state is-stitcher-required">
        <div className="processing-state-icon" aria-hidden="true">360°</div>
        <strong>รับไฟล์ INSV ต้นฉบับเรียบร้อยแล้ว</strong>
        <p>ไฟล์ดิบคือข้อมูลหลักสำหรับ Stitch ภาพสองเลนส์และอ่าน IMU เพื่อคำนวณเส้นทางสัมพัทธ์ จากนั้นระบบต้องจัดแนวเส้นทางกับแปลนก่อนแสดงจุดวาร์ปจริง</p>
        <small>กำลังรอ Insta360 MediaSDK สำหรับ X5 ซึ่งติดตั้งแยกจาก Insta360 Studio ไฟล์ต้นฉบับถูกเก็บไว้ครบและไม่ต้องอัปโหลดใหม่</small>
        <div className="raw-pipeline-steps">
          <span>INSV สองเลนส์ + IMU</span><i>→</i><span>Stitch + Visual-Inertial SLAM</span><i>→</i><span>จัดแนวแปลน</span><i>→</i><span>จุดวาร์ป</span>
        </div>
        {canUpload && (
          <details className="mp4-research-fallback">
            <summary>โหมดทดลองด้วย MP4 (ไม่ใช้ IMU และต้องจัดแนวบนแปลน 2 จุด)</summary>
            <p>ใช้ทดสอบ Viewer และ Visual SfM เท่านั้น ไม่ใช่เส้นทางที่แนะนำสำหรับผลวิจัยความแม่นยำ</p>
            <StitchedVideoUploader canUpload captureId={captureId} projectId={projectId} />
          </details>
        )}
      </section>
    );
  }

  if (failed) {
    return (
      <section className="capture-processing-state is-failed">
        <div className="processing-state-icon" aria-hidden="true">!</div>
        <strong>ประมวลผลไฟล์ไม่สำเร็จ</strong>
        <p>{job.error_message || "ตรวจสอบ Worker และรูปแบบไฟล์ แล้วกด Retry Processing"}</p>
      </section>
    );
  }

  return (
    <section className="capture-processing-state">
      <div className="processing-state-spinner" aria-hidden="true" />
      <strong>กำลังเตรียมภาพ 360</strong>
      <p>เมื่อประมวลผลไฟล์และระบุตำแหน่งสำเร็จ ระบบจะแสดงภาพ เส้นทาง และจุดวาร์ปที่เชื่อมกันบนแปลน</p>
    </section>
  );
}

export default async function CaptureViewerPage({ params, searchParams }: { params: Promise<{ projectId: string; captureId: string }>; searchParams: Promise<{ panel?: string; keyframe?: string; mode?: string; floorId?: string }> }) {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  const { projectId, captureId } = await params;
  const { panel, keyframe, mode, floorId } = await searchParams;
  const [project, detail, floors, bimModels, captures] = await Promise.all([
    getProject(projectId),
    getCaptureDetail(projectId, captureId),
    getFloors(projectId),
    getBimModels(projectId).catch(() => ({ active: null, versions: [] })),
    getCaptures(projectId),
  ]);
  const job = detail.jobs[0];
  const capturedAt = new Date(detail.capture.captured_at).toLocaleString("th-TH");
  const captureDate = detail.capture.captured_at.slice(0, 10);
  const availableFloors = floors.filter((floor) => (
    !floor.available_from || floor.available_from <= captureDate
  ));
  const hasEvidence = detail.keyframes.length > 0;
  const canUpload = project.role === "admin" || project.role === "reviewer";
  const canEditProgress = canUpload || project.role === "sub_admin";
  const schedules = await getSchedules(projectId).catch(() => []);
  const schedule = schedules.find((item) => item.is_baseline && item.status === "READY")
    ?? schedules.find((item) => item.status === "READY")
    ?? null;
  const [activities, humanProgress] = schedule
    ? await Promise.all([getActivities(projectId, schedule.id), getHumanProgress(projectId)])
    : [[], []];
  const activeFloorId = availableFloors.some((item) => item.id === floorId)
    ? floorId!
    : detail.capture.start_floor_id ?? availableFloors[0]?.id ?? null;
  const beamProgress = activeFloorId
    ? await getBeamProgress(projectId, captureId, activeFloorId).catch(() => null)
    : null;
  const columnProgress = activeFloorId
    ? await getColumnProgress(projectId, captureId, activeFloorId).catch(() => null)
    : null;
  const slabProgress = activeFloorId
    ? await getSlabProgress(projectId, captureId, activeFloorId).catch(() => null)
    : null;
  const structuralElements = activeFloorId
    ? await getStructuralElements(projectId, activeFloorId).catch(() => [])
    : [];

  return (
    <div className="app-frame">
      <AppHeader user={user} viewerTitle={`${project.name} · ${capturedAt}`} />
      <div className="workspace viewer-workspace">
        <ViewerIconRail captureId={captureId} projectId={projectId} />
        <main className="workspace-main viewer-page">
          <div className="viewer-topbar">
            <div>
              <strong>{capturedAt}</strong>
              <span>{detail.capture.captured_by_text || "ไม่ระบุกล้อง"}</span>
            </div>
            {detail.metadata && (
              <div className="viewer-metrics">
                <span>{detail.metadata.width_px}×{detail.metadata.height_px}</span>
                <span>{(detail.metadata.duration_ms / 1000).toFixed(1)} วินาที</span>
                <span>{Number(detail.metadata.fps).toFixed(2)} FPS</span>
                <span>{detail.metadata.codec_name.toUpperCase()}</span>
              </div>
            )}
            <JobStatus captureId={captureId} captureStatus={detail.capture.status} job={job} projectId={projectId} />
          </div>
          <ViewerCaptureNavigator activePlanFloorId={activeFloorId} captures={captures} currentCaptureId={captureId} floors={floors} progressOpen={panel === "progress"} projectId={projectId} />
          {hasEvidence ? (
            <CaptureReviewWorkspace
              canEdit={canUpload}
              activities={activities}
              canManageBim={project.role === "admin"}
              canEditProgress={canEditProgress}
              canEditProgressQuantities={project.role === "admin" || project.role === "sub_admin"}
              bimModel={bimModels.active}
              captureId={captureId}
              detail={detail}
              floors={availableFloors}
              humanProgress={humanProgress}
              beamProgress={beamProgress}
              columnProgress={columnProgress}
              slabProgress={slabProgress}
              structuralElements={structuralElements}
              initialKeyframeId={detail.keyframes.some((item) => item.id === keyframe) ? keyframe : null}
              initialFloorId={availableFloors.some((item) => item.id === floorId) ? floorId : detail.capture.start_floor_id}
              initialViewMode={mode === "track" ? "track" : undefined}
              initialProgressOpen={panel === "progress"}
              key={`${captureId}:${activeFloorId ?? "no-floor"}:${detail.capture.status}:${job?.id ?? "no-job"}:${job?.status ?? "no-status"}:${panel ?? "viewer"}`}
              projectId={projectId}
            />
          ) : (
            <EmptyCaptureState canUpload={canUpload} captureId={captureId} captureStatus={detail.capture.status} job={job} projectId={projectId} />
          )}
        </main>
      </div>
    </div>
  );
}
