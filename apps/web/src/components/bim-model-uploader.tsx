"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";

export function BimModelUploader({ projectId, compact = false }: { projectId: string; compact?: boolean }) {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function upload(file: File) {
    setBusy(true);
    setMessage("กำลังอัปโหลดและตรวจไฟล์ IFC…");
    try {
      const formData = new FormData();
      formData.set("file", file);
      const response = await fetch(`/api/projects/${projectId}/bim-models`, {
        method: "POST",
        body: formData,
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(body?.detail || "อัปโหลด IFC ไม่สำเร็จ");
      setMessage(`เพิ่ม ${body.name} เป็น BIM รุ่น ${body.version_no} แล้ว`);
      router.refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "อัปโหลด IFC ไม่สำเร็จ");
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  return (
    <div className={`bim-upload ${compact ? "is-compact" : ""}`}>
      <input
        accept=".ifc,application/x-step"
        aria-label="เลือกไฟล์ IFC"
        hidden
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) void upload(file);
        }}
        ref={inputRef}
        type="file"
      />
      <button disabled={busy} onClick={() => inputRef.current?.click()} type="button">
        {busy ? "กำลังเพิ่ม BIM…" : compact ? "เปลี่ยน IFC" : "เพิ่มโมเดล IFC"}
      </button>
      {message && <small role="status">{message}</small>}
    </div>
  );
}
