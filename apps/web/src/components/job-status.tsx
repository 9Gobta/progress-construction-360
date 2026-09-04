"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import type { ProcessingJob } from "@/lib/types";

type JobStatusProps = {
  projectId: string;
  captureId: string;
  captureStatus: string;
  job: ProcessingJob | undefined;
};

export function JobStatus({ projectId, captureId, captureStatus, job }: JobStatusProps) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const needsStitcher = captureStatus === "STITCHER_REQUIRED"
    || (job?.status === "FAILED" && job.error_code === "Insta360StitcherUnavailable");

  useEffect(() => {
    if (!job || !["QUEUED", "RUNNING"].includes(job.status)) return;
    const timer = window.setInterval(() => router.refresh(), 5000);
    return () => window.clearInterval(timer);
  }, [job, router]);

  async function retry() {
    if (!job) return;
    setBusy(true);
    setError(null);
    const response = await fetch(`/api/projects/${projectId}/captures/${captureId}/jobs/${job.id}/retry`, { method: "POST" });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) setError(body.detail || "สั่งประมวลผลใหม่ไม่สำเร็จ");
    else router.refresh();
    setBusy(false);
  }

  const displayStatus = needsStitcher ? "STITCHER REQUIRED" : (job?.status ?? "NO JOB");
  return (
    <div className="job-status-card">
      <div className={needsStitcher ? "is-stitcher-required" : ""}>
        <span>Processing</span>
        <strong>{displayStatus}</strong>
        <small>{job ? `${Number(job.progress_percent)}% · Attempt ${job.attempt_no}` : "รอให้อัปโหลดครบ"}</small>
        {job?.status === "FAILED" && job.error_message && <p className="job-error-detail">{job.error_message}</p>}
      </div>
      {job?.status === "FAILED" && !needsStitcher && (
        <button className="button button-secondary" disabled={busy} onClick={retry} type="button">
          {busy ? "กำลัง Retry..." : "Retry Processing"}
        </button>
      )}
      {error && <p className="form-error">{error}</p>}
    </div>
  );
}
