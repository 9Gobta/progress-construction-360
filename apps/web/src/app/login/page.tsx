import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { AppHeader } from "@/components/app-header";
import { AuthForm } from "@/components/auth-form";
import { getCurrentUser } from "@/lib/server-api";

export const metadata: Metadata = { title: "เข้าสู่ระบบ" };

export default async function LoginPage() {
  const user = await getCurrentUser();
  if (user) redirect("/projects");

  return (
    <div className="app-frame">
      <AppHeader user={null} />
      <main className="auth-shell">
        <aside className="auth-aside">
          <p className="eyebrow">HUMAN-VERIFIED PROGRESS</p>
          <h1>ตรวจงานโครงสร้างจากภาพ 360 โดยทีมโครงการ</h1>
          <p>
            ระบบเก็บผลตรวจพร้อมวัน เวลา ผู้ตรวจ และภาพหลักฐาน
            เพื่อย้อนกลับไปตรวจสอบและเปรียบเทียบกับแผนได้อย่างโปร่งใส
          </p>
        </aside>
        <section className="auth-main"><AuthForm /></section>
      </main>
    </div>
  );
}
