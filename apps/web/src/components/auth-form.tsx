"use client";

import { FormEvent, useState, useSyncExternalStore } from "react";
import { useRouter } from "next/navigation";

const subscribeToHydration = () => () => undefined;

export function AuthForm() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const ready = useSyncExternalStore(
    subscribeToHydration,
    () => true,
    () => false,
  );

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setPending(true);
    const form = new FormData(event.currentTarget);
    const payload = {
      email: String(form.get("email") ?? ""),
      password: String(form.get("password") ?? ""),
      ...(mode === "register" ? { display_name: String(form.get("display_name") ?? "") } : {}),
    };

    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 20_000);
    try {
      const response = await fetch(`/api/session/${mode}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });
      const contentType = response.headers.get("content-type") ?? "";
      const body = contentType.includes("application/json")
        ? await response.json()
        : null;
      if (!response.ok) {
        const serviceUnavailable = response.status >= 500;
        throw new Error(
          body?.detail ??
            (serviceUnavailable
              ? "เซิร์ฟเวอร์กำลังหยุดทำงาน กรุณาแจ้งผู้ดูแลระบบและลองใหม่"
              : "ไม่สามารถเข้าสู่ระบบได้"),
        );
      }
      if (!body) throw new Error("เซิร์ฟเวอร์ตอบกลับไม่สมบูรณ์ กรุณาลองใหม่");
      router.push("/projects");
      router.refresh();
    } catch (reason) {
      setError(
        reason instanceof DOMException && reason.name === "AbortError"
          ? "การเชื่อมต่อใช้เวลานานเกินไป กรุณารีเฟรชหน้าแล้วลองอีกครั้ง"
          : reason instanceof Error
            ? reason.message
            : "เกิดข้อผิดพลาด กรุณาลองอีกครั้ง",
      );
    } finally {
      window.clearTimeout(timeout);
      setPending(false);
    }
  }

  return (
    <div className="auth-card">
      <h2>{mode === "login" ? "ยินดีต้อนรับกลับ" : "สร้างบัญชีผู้ดูแล"}</h2>
      <p>เข้าสู่พื้นที่โครงการและเริ่มเตรียมข้อมูลชั้น 1</p>
      <div className="auth-tabs" role="tablist" aria-label="เลือกรูปแบบบัญชี">
        <button type="button" role="tab" aria-selected={mode === "login"} onClick={() => { setMode("login"); setError(null); }}>
          เข้าสู่ระบบ
        </button>
        <button type="button" role="tab" aria-selected={mode === "register"} onClick={() => { setMode("register"); setError(null); }}>
          สร้างบัญชี
        </button>
      </div>
      <form className="form-stack" method="post" onSubmit={submit}>
        {mode === "register" && (
          <div className="field">
            <label htmlFor="display_name">ชื่อที่แสดง</label>
            <input id="display_name" name="display_name" minLength={2} maxLength={120} required />
          </div>
        )}
        <div className="field">
          <label htmlFor="email">อีเมล</label>
          <input id="email" name="email" type="email" autoComplete="email" required />
        </div>
        <div className="field">
          <label htmlFor="password">รหัสผ่าน</label>
          <input
            id="password"
            name="password"
            type="password"
            minLength={mode === "register" ? 10 : 1}
            maxLength={128}
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            required
          />
        </div>
        {error && <p className="form-error" role="alert">{error}</p>}
        <button className="button button-primary button-block" disabled={pending || !ready} type="submit">
          {!ready
            ? "กำลังเตรียมระบบ…"
            : pending
              ? "กำลังดำเนินการ…"
              : mode === "login"
                ? "เข้าสู่ระบบ"
                : "สร้างบัญชีและเข้าสู่ระบบ"}
        </button>
      </form>
    </div>
  );
}
