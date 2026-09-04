"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

export function AuthForm() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

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

    try {
      const response = await fetch(`/api/session/${mode}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail ?? "ไม่สามารถเข้าสู่ระบบได้");
      router.push("/projects");
      router.refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "เกิดข้อผิดพลาด กรุณาลองอีกครั้ง");
    } finally {
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
      <form className="form-stack" onSubmit={submit}>
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
        <button className="button button-primary button-block" disabled={pending} type="submit">
          {pending ? "กำลังดำเนินการ…" : mode === "login" ? "เข้าสู่ระบบ" : "สร้างบัญชีและเข้าสู่ระบบ"}
        </button>
      </form>
    </div>
  );
}

