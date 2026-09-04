"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

export function CreateProjectForm() {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError(null);
    const target = event.currentTarget;
    const data = new FormData(target);
    try {
      const response = await fetch("/api/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: String(data.get("name") ?? ""),
          location: String(data.get("location") ?? "") || null,
          timezone: "Asia/Bangkok",
          description: String(data.get("description") ?? "") || null,
        }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail ?? "สร้างโครงการไม่สำเร็จ");
      target.reset();
      router.push(`/projects/${body.id}/settings`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "เกิดข้อผิดพลาด กรุณาลองอีกครั้ง");
    } finally {
      setPending(false);
    }
  }

  return (
    <form className="form-stack" onSubmit={submit}>
      <div className="field">
        <label htmlFor="project-name">ชื่อโครงการ</label>
        <input id="project-name" name="name" defaultValue="อาคารหอพัก ค.ส.ล. 4 ชั้น" minLength={2} maxLength={200} required />
      </div>
      <div className="field"><label htmlFor="project-location">ที่ตั้ง</label><input id="project-location" name="location" maxLength={300} /></div>
      <div className="field"><label htmlFor="project-description">คำอธิบาย</label><textarea id="project-description" name="description" maxLength={3000} /></div>
      {error && <p className="form-error" role="alert">{error}</p>}
      <button className="button button-primary button-block" disabled={pending} type="submit">
        {pending ? "กำลังสร้าง…" : "สร้างโครงการ"}
      </button>
    </form>
  );
}
