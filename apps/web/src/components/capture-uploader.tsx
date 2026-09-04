"use client";

import Image from "next/image";
import Link from "next/link";
import { FormEvent, MouseEvent, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import type { Capture, Floor, MultipartInitiate, MultipartStatus, StorageStatus } from "@/lib/types";

type Props = {
  projectId: string;
  role: "admin" | "sub_admin" | "reviewer" | "viewer" | null;
  floors: Floor[];
  captures: Capture[];
  storageStatus: StorageStatus | null;
};

type ActiveUpload = {
  mediaId: string;
  partSize: number;
  partCount: number;
  captureCreated: boolean;
};

async function jsonResponse<T>(response: Response): Promise<T> {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || "เกิดข้อผิดพลาด กรุณาลองใหม่");
  return body as T;
}

function localDateTimeValue() {
  const now = new Date(Date.now() - new Date().getTimezoneOffset() * 60_000);
  return now.toISOString().slice(0, 16);
}

function uploadContentType() {
  return "video/mp4";
}

function formatGiB(bytes: number | null) {
  return bytes === null ? "ไม่ทราบ" : `${(bytes / 1024 ** 3).toFixed(1)} GB`;
}

function bangkokDateKey(value: string) {
  return new Intl.DateTimeFormat("en-CA", {
    day: "2-digit",
    month: "2-digit",
    timeZone: "Asia/Bangkok",
    year: "numeric",
  }).format(new Date(value));
}

function captureDateLabel(value: string) {
  return new Intl.DateTimeFormat("th-TH", {
    day: "numeric",
    month: "numeric",
    timeZone: "Asia/Bangkok",
    year: "numeric",
  }).format(new Date(value));
}

export function CaptureUploader({ projectId, role, floors, captures, storageStatus }: Props) {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [fileInputKey, setFileInputKey] = useState(0);
  const [floorId, setFloorId] = useState(floors[0]?.id ?? "");
  const [point, setPoint] = useState<{ x: number; y: number } | null>(null);
  const [capturedAt, setCapturedAt] = useState(localDateTimeValue);
  const [datasetSplit, setDatasetSplit] = useState<"DEVELOPMENT" | "HOLDOUT_TEST">("DEVELOPMENT");
  const [camera, setCamera] = useState("Insta360 X5");
  const [notes, setNotes] = useState("");
  const [activeUpload, setActiveUpload] = useState<ActiveUpload | null>(null);
  const [uploadPercent, setUploadPercent] = useState(0);
  const [busy, setBusy] = useState(false);
  const [deletingCaptureId, setDeletingCaptureId] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [newFloorName, setNewFloorName] = useState("");
  const [newFloorIndex, setNewFloorIndex] = useState("1");

  const canUpload = (role === "admin" || role === "reviewer") && storageStatus?.upload_allowed !== false;
  const floorById = useMemo(
    () => new Map(floors.map((floor) => [floor.id, floor])),
    [floors],
  );
  const captureGroups = useMemo(() => {
    const groups = new Map<string, Capture[]>();
    for (const capture of captures) {
      const key = bangkokDateKey(capture.captured_at);
      groups.set(key, [...(groups.get(key) ?? []), capture]);
    }
    return Array.from(groups.entries()).map(([dateKey, rows]) => ({
      dateKey,
      rows: [...rows].sort((first, second) => {
        const firstFloor = floorById.get(first.start_floor_id)?.level_index ?? 999;
        const secondFloor = floorById.get(second.start_floor_id)?.level_index ?? 999;
        return firstFloor - secondFloor || first.captured_at.localeCompare(second.captured_at);
      }),
    }));
  }, [captures, floorById]);

  async function deleteCapture(capture: Capture) {
    const capturedAtLabel = new Date(capture.captured_at).toLocaleString("th-TH");
    if (!window.confirm(`ลบ Capture วันที่ ${capturedAtLabel} ใช่หรือไม่?\n\nวิดีโอ ภาพ 360 เส้นทาง และผลประมวลผลของรายการนี้จะถูกลบถาวร`)) return;
    setDeletingCaptureId(capture.id);
    setMessage(null);
    try {
      const response = await fetch(`/api/projects/${projectId}/captures/${capture.id}`, {
        method: "DELETE",
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || "ลบ Capture ไม่สำเร็จ");
      }
      setMessage(`ลบ Capture วันที่ ${capturedAtLabel} แล้ว`);
      router.refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ลบ Capture ไม่สำเร็จ");
    } finally {
      setDeletingCaptureId(null);
    }
  }

  async function addFloor(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      await jsonResponse(await fetch(`/api/projects/${projectId}/floors`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: newFloorName, level_index: Number(newFloorIndex) }),
      }));
      setNewFloorName("");
      setMessage("เพิ่มชั้นแล้ว");
      router.refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "เพิ่มชั้นไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  }

  function selectStartPoint(event: MouseEvent<HTMLDivElement>) {
    const bounds = event.currentTarget.getBoundingClientRect();
    setPoint({
      x: Math.min(1, Math.max(0, (event.clientX - bounds.left) / bounds.width)),
      y: Math.min(1, Math.max(0, (event.clientY - bounds.top) / bounds.height)),
    });
  }

  async function putPart(url: string, body: Blob) {
    let lastError: Error | null = null;
    for (let attempt = 1; attempt <= 3; attempt += 1) {
      try {
        const response = await fetch(url, { method: "PUT", body });
        if (!response.ok) throw new Error(`Upload part ล้มเหลว (${response.status})`);
        return;
      } catch (error) {
        lastError = error instanceof Error ? error : new Error("Upload part ล้มเหลว");
      }
    }
    throw lastError;
  }

  async function uploadMissingParts(context: ActiveUpload, selectedFile: File) {
    const statusUrl = `/api/projects/${projectId}/media/${context.mediaId}/multipart`;
    const current = await jsonResponse<MultipartStatus>(await fetch(statusUrl));
    const completed = new Set(current.uploaded_parts.map((part) => part.part_number));
    setUploadPercent(Math.round((completed.size / context.partCount) * 100));
    const missing = Array.from({ length: context.partCount }, (_, index) => index + 1)
      .filter((part) => !completed.has(part));

    for (let offset = 0; offset < missing.length; offset += 50) {
      const batch = missing.slice(offset, offset + 50);
      const signed = await jsonResponse<MultipartStatus>(await fetch(`${statusUrl}/parts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ part_numbers: batch }),
      }));
      let cursor = 0;
      const workers = Array.from({ length: Math.min(3, signed.upload_urls.length) }, async () => {
        while (cursor < signed.upload_urls.length) {
          const item = signed.upload_urls[cursor];
          cursor += 1;
          const start = (item.part_number - 1) * context.partSize;
          const end = Math.min(selectedFile.size, start + context.partSize);
          await putPart(item.url, selectedFile.slice(start, end));
          completed.add(item.part_number);
          setUploadPercent(Math.round((completed.size / context.partCount) * 100));
        }
      });
      await Promise.all(workers);
    }

    const finished = await jsonResponse<MultipartStatus>(await fetch(statusUrl));
    if (finished.uploaded_parts.length !== context.partCount) {
      throw new Error("เซิร์ฟเวอร์ยังตรวจพบ Parts ไม่ครบ กด Retry เพื่อส่งเฉพาะส่วนที่ขาด");
    }
    await jsonResponse(await fetch(`${statusUrl}/complete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        parts: finished.uploaded_parts.map((part) => ({
          part_number: part.part_number,
          etag: part.etag,
        })),
      }),
    }));
  }

  async function submitCapture(event: FormEvent) {
    event.preventDefault();
    if (!file || !point || !floorId) return;
    setBusy(true);
    setMessage(null);
    let context = activeUpload;
    try {
      if (!context) {
        const initiated = await jsonResponse<MultipartInitiate>(await fetch(`/api/projects/${projectId}/media/multipart`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            original_filename: file.name,
            content_type: uploadContentType(),
            size_bytes: file.size,
          }),
        }));
        context = {
          mediaId: initiated.media.id,
          partSize: initiated.part_size_bytes,
          partCount: initiated.part_count,
          captureCreated: false,
        };
        setActiveUpload(context);
      }
      if (!context.captureCreated) {
        await jsonResponse(await fetch(`/api/projects/${projectId}/captures`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            source_video_id: context.mediaId,
            captured_at: new Date(capturedAt).toISOString(),
            captured_by_text: camera.trim() || null,
            start_floor_id: floorId,
            start_x: point.x,
            start_y: point.y,
            notes: notes.trim() || null,
            dataset_split: datasetSplit,
          }),
        }));
        context = { ...context, captureCreated: true };
        setActiveUpload(context);
      }
      await uploadMissingParts(context, file);
      setMessage("อัปโหลดครบแล้ว ระบบสร้างงานตรวจวิดีโอและเข้าคิวประมวลผลแล้ว");
      setUploadPercent(100);
      setActiveUpload(null);
      setFile(null);
      setFileInputKey((value) => value + 1);
      router.refresh();
    } catch (error) {
      setMessage(`${error instanceof Error ? error.message : "Upload ไม่สำเร็จ"} — เลือกไฟล์เดิมไว้แล้วกด Retry ได้`);
    } finally {
      setBusy(false);
    }
  }

  async function resumeExisting(mediaId: string) {
    if (!file) {
      setMessage("กรุณาเลือกไฟล์ MP4 เดิมก่อนกด Resume");
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      const statusUrl = `/api/projects/${projectId}/media/${mediaId}/multipart`;
      const current = await jsonResponse<MultipartStatus>(await fetch(statusUrl));
      if (current.size_bytes !== file.size || current.original_filename !== file.name) {
        throw new Error(`ต้องเลือกไฟล์เดิมชื่อ ${current.original_filename} ขนาด ${current.size_bytes} bytes`);
      }
      const context = {
        mediaId,
        partSize: current.part_size_bytes,
        partCount: current.part_count,
        captureCreated: true,
      };
      setActiveUpload(context);
      await uploadMissingParts(context, file);
      setMessage("Resume สำเร็จ ไฟล์ครบและเข้าคิวประมวลผลแล้ว");
      setUploadPercent(100);
      setActiveUpload(null);
      setFile(null);
      setFileInputKey((value) => value + 1);
      router.refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Resume ไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="capture-stack">
      {message && <p className="notice" role="status">{message}</p>}
      {storageStatus && (
        <section className={`storage-health ${storageStatus.upload_allowed ? "is-safe" : "is-critical"}`}>
          <div>
            <strong>{storageStatus.upload_allowed ? "พื้นที่จัดเก็บพร้อมใช้งาน" : "หยุดอัปโหลดชั่วคราว — พื้นที่ใกล้เต็ม"}</strong>
            <p>{storageStatus.message}</p>
          </div>
          <div className="storage-health-metrics">
            <span>Provider <b>{storageStatus.provider}</b></span>
            <span>ไฟล์โครงการ <b>{formatGiB(storageStatus.project_object_bytes)}</b></span>
            <span>พื้นที่ว่าง <b>{formatGiB(storageStatus.disk_free_bytes)}</b></span>
            <span>ต้องสำรองอย่างน้อย <b>{formatGiB(storageStatus.minimum_free_bytes)}</b></span>
          </div>
        </section>
      )}
      {!floors.length && role === "admin" && (
        <section className="panel floor-setup">
          <div><h2>เพิ่มชั้นก่อนอัปโหลด</h2><p>เพิ่มทีละชั้น แล้วเลือกชั้นเริ่มต้นของวิดีโอ</p></div>
          <form onSubmit={addFloor}>
            <label className="field"><span>ชื่อชั้น</span><input onChange={(event) => setNewFloorName(event.target.value)} placeholder="เช่น ชั้น 1" required value={newFloorName} /></label>
            <label className="field"><span>ลำดับชั้น</span><input min="-10" onChange={(event) => setNewFloorIndex(event.target.value)} required type="number" value={newFloorIndex} /></label>
            <button className="button button-primary" disabled={busy} type="submit">เพิ่มชั้น</button>
          </form>
        </section>
      )}

      <section className="panel capture-upload-panel">
          <div className="panel-header"><div><h2>อัปโหลด Capture 360°</h2><p>รองรับ MP4 360 แบบ Equirectangular 2:1 ที่ Stitch แล้ว</p></div><span className="source-badge">SPATIAL CAPTURE</span></div>
        <form className="capture-form" onSubmit={submitCapture}>
          <div className="capture-fields">
            <label className="field"><span>วิดีโอ MP4 แบบ 360 Equirectangular</span><input accept="video/mp4,.mp4" disabled={!canUpload || busy || activeUpload !== null} key={fileInputKey} onChange={(event) => { setFile(event.target.files?.[0] ?? null); setActiveUpload(null); setUploadPercent(0); }} required type="file" /></label>
            <label className="field"><span>วันที่ถ่าย</span><input disabled={!canUpload || busy} onChange={(event) => setCapturedAt(event.target.value)} required type="datetime-local" value={capturedAt} /></label>
            <label className="field"><span>ชุดข้อมูล</span><select disabled={!canUpload || busy} onChange={(event) => setDatasetSplit(event.target.value as "DEVELOPMENT" | "HOLDOUT_TEST")} value={datasetSplit}><option value="DEVELOPMENT">ชุดใช้งานโครงการ</option><option value="HOLDOUT_TEST">ชุดทดสอบความแม่นยำเส้นทาง</option></select></label>
            <label className="field"><span>ชั้นที่ถ่าย (ห้ามเดินข้ามชั้น)</span><select disabled={!canUpload || busy || !floors.length} onChange={(event) => setFloorId(event.target.value)} required value={floorId}><option value="">เลือกชั้น</option>{floors.map((floor) => <option key={floor.id} value={floor.id}>{floor.name}</option>)}</select></label>
            <label className="field"><span>กล้อง/ผู้ถ่าย</span><input disabled={!canUpload || busy} maxLength={200} onChange={(event) => setCamera(event.target.value)} value={camera} /></label>
            <label className="field"><span>หมายเหตุ</span><textarea disabled={!canUpload || busy} maxLength={3000} onChange={(event) => setNotes(event.target.value)} value={notes} /></label>
            <div className="upload-progress"><span>Upload progress</span><strong>{uploadPercent}%</strong><div><i style={{ width: `${uploadPercent}%` }} /></div></div>
            <button className="button button-primary button-block" disabled={!file || !point || !floorId || !canUpload || busy} type="submit">{busy ? `กำลังอัปโหลด ${uploadPercent}%` : activeUpload ? "Retry / Resume Upload" : "สร้าง Capture และอัปโหลด"}</button>
            <p className="panel-note">ระบบจะดึงภาพทุก 1 วินาที สร้าง Camera Pose และจัดแนวกับ Capture เดิม; ถ้าความมั่นใจต่ำจะให้ตรวจแก้ก่อนแสดงเส้นทาง</p>
          </div>
          <div>
            <p className="plan-instruction">คลิกจุดเริ่มต้นบนแบบหนึ่งครั้ง</p>
            <div className="start-point-plan" onClick={selectStartPoint} role="button" tabIndex={0}>
              <Image alt="แบบโครงสร้างชั้น 1 สำหรับเลือกจุดเริ่มต้น" fill priority sizes="(max-width: 920px) 100vw, 55vw" src="/plans/floor-1-structural.png" />
              {point && <span className="selected-start" style={{ left: `${point.x * 100}%`, top: `${point.y * 100}%` }} />}
            </div>
            <p className="coordinate-readout">{point ? `จุดเริ่มต้น x=${point.x.toFixed(3)}, y=${point.y.toFixed(3)}` : "ยังไม่ได้เลือกจุดเริ่มต้น"}</p>
          </div>
        </form>
      </section>

      <section className="panel">
        <div className="panel-header"><h2>Capture ทั้งหมด</h2><span>{captureGroups.length} วัน · {captures.length} ไฟล์</span></div>
        {captures.length ? (
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th>วันที่ถ่าย</th><th>กล้อง/ผู้ถ่าย</th><th>ชุดข้อมูล</th><th>ชั้นที่มีข้อมูล</th><th>สถานะรวม</th><th>Action</th></tr></thead>
              <tbody>{captureGroups.map((group) => {
                const firstCapture = group.rows[0];
                const cameras = Array.from(new Set(group.rows.map((capture) => capture.captured_by_text).filter(Boolean)));
                const floorNames = Array.from(new Set(group.rows.map((capture) => floorById.get(capture.start_floor_id)?.name ?? "ไม่ระบุชั้น")));
                const statuses = Array.from(new Set(group.rows.map((capture) => capture.status)));
                const hasHoldout = group.rows.some((capture) => capture.dataset_split === "HOLDOUT_TEST");
                return (
                  <tr key={group.dateKey}>
                    <td><strong>{captureDateLabel(firstCapture.captured_at)}</strong><small className="capture-day-count">{group.rows.length} ไฟล์</small></td>
                    <td>{cameras.join(", ") || "—"}</td>
                    <td><span className={`dataset-split ${hasHoldout ? "is-holdout" : ""}`}>{hasHoldout ? "ชุดทดสอบ" : "ชุดพัฒนา"}</span></td>
                    <td><div className="capture-floor-badges">{floorNames.map((name) => <span key={name}>{name}</span>)}</div></td>
                    <td><span className={`capture-status ${statuses.length === 1 ? `status-${statuses[0].toLowerCase()}` : "status-mixed"}`}>{statuses.length === 1 ? statuses[0] : `หลายสถานะ (${statuses.length})`}</span></td>
                    <td>
                      <div className="capture-row-actions">
                        <Link className="button button-ghost" href={`/projects/${projectId}/captures/${firstCapture.id}`}>เปิด Viewer</Link>
                        <details className="capture-day-manage">
                          <summary>จัดการไฟล์</summary>
                          <div>{group.rows.map((capture) => (
                            <div key={capture.id}>
                              <span>{floorById.get(capture.start_floor_id)?.name ?? "ไม่ระบุชั้น"}</span>
                              {capture.status === "UPLOADING"
                                ? <button disabled={busy || !file} onClick={() => resumeExisting(capture.source_video_id)} type="button">Resume</button>
                                : <Link href={`/projects/${projectId}/captures/${capture.id}`}>เปิด</Link>}
                              {role === "admin" && <button className="is-danger" disabled={deletingCaptureId !== null} onClick={() => deleteCapture(capture)} type="button">{deletingCaptureId === capture.id ? "กำลังลบ..." : "ลบ"}</button>}
                            </div>
                          ))}</div>
                        </details>
                      </div>
                    </td>
                  </tr>
                );
              })}</tbody>
            </table>
          </div>
        ) : <div className="empty-state"><strong>ยังไม่มี Capture</strong><p>เลือก MP4 360, ชั้น และจุดเริ่มต้นเพื่ออัปโหลดวิดีโอแรก</p></div>}
      </section>
    </div>
  );
}
