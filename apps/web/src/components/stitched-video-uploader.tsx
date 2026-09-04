"use client";

import { ChangeEvent, useState } from "react";
import { useRouter } from "next/navigation";

import type { MultipartInitiate, MultipartStatus } from "@/lib/types";

type Props = {
  projectId: string;
  captureId: string;
  canUpload: boolean;
};

async function responseJson<T>(response: Response): Promise<T> {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || "อัปโหลดไม่สำเร็จ");
  return body as T;
}

async function putPart(url: string, body: Blob) {
  let lastError: Error | null = null;
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    try {
      const response = await fetch(url, { method: "PUT", body });
      if (!response.ok) throw new Error(`ส่งข้อมูลไม่สำเร็จ (${response.status})`);
      return;
    } catch (error) {
      lastError = error instanceof Error ? error : new Error("ส่งข้อมูลไม่สำเร็จ");
    }
  }
  throw lastError;
}

export function StitchedVideoUploader({ projectId, captureId, canUpload }: Props) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".mp4")) {
      setError("กรุณาเลือกไฟล์ MP4 แบบ 360 ที่ Export จาก Insta360 Studio");
      return;
    }

    setBusy(true);
    setProgress(0);
    setError(null);
    try {
      const initiated = await responseJson<MultipartInitiate>(await fetch(`/api/projects/${projectId}/media/multipart`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          original_filename: file.name,
          content_type: "video/mp4",
          size_bytes: file.size,
        }),
      }));

      await responseJson(await fetch(`/api/projects/${projectId}/captures/${captureId}/stitched-media`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ media_id: initiated.media.id }),
      }));

      const statusUrl = `/api/projects/${projectId}/media/${initiated.media.id}/multipart`;
      const partNumbers = Array.from({ length: initiated.part_count }, (_, index) => index + 1);
      const completed = new Set<number>();
      for (let offset = 0; offset < partNumbers.length; offset += 50) {
        const signed = await responseJson<MultipartStatus>(await fetch(`${statusUrl}/parts`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ part_numbers: partNumbers.slice(offset, offset + 50) }),
        }));
        let cursor = 0;
        const workers = Array.from({ length: Math.min(3, signed.upload_urls.length) }, async () => {
          while (cursor < signed.upload_urls.length) {
            const part = signed.upload_urls[cursor];
            cursor += 1;
            const start = (part.part_number - 1) * initiated.part_size_bytes;
            const end = Math.min(file.size, start + initiated.part_size_bytes);
            await putPart(part.url, file.slice(start, end));
            completed.add(part.part_number);
            setProgress(Math.round((completed.size / initiated.part_count) * 100));
          }
        });
        await Promise.all(workers);
      }

      const uploaded = await responseJson<MultipartStatus>(await fetch(statusUrl));
      if (uploaded.uploaded_parts.length !== initiated.part_count) {
        throw new Error("เซิร์ฟเวอร์ได้รับข้อมูลไม่ครบ กรุณาเลือกไฟล์เดิมและลองอีกครั้ง");
      }
      await responseJson(await fetch(`${statusUrl}/complete`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          parts: uploaded.uploaded_parts.map((part) => ({
            part_number: part.part_number,
            etag: part.etag,
          })),
        }),
      }));
      setProgress(100);
      router.refresh();
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : "อัปโหลดไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  }

  if (!canUpload) return null;
  return (
    <div className="stitched-video-upload">
      <label className={`button button-primary ${busy ? "is-disabled" : ""}`}>
        {busy ? `กำลังอัปโหลด ${progress}%` : "เลือก MP4 360 ที่ Export แล้ว"}
        <input accept="video/mp4,.mp4" disabled={busy} onChange={upload} type="file" />
      </label>
      {busy && <div className="stitched-upload-progress"><i style={{ width: `${progress}%` }} /></div>}
      {error && <p className="form-error">{error}</p>}
    </div>
  );
}
