import Link from "next/link";

import { AppHeader } from "@/components/app-header";
import { getApiHealth, getCurrentUser } from "@/lib/server-api";

const setupSteps = [
  { number: "01", title: "สร้างโครงการ", detail: "ชื่อ ที่ตั้ง เขตเวลา และสมาชิกโครงการ" },
  { number: "02", title: "อัปโหลดแบบและ Schedule", detail: "กำหนดชั้น Grid และนำเข้า Excel จาก MS Project" },
  { number: "03", title: "อัปโหลด Capture 360°", detail: "เลือกชั้นและคลิกจุดเริ่มต้นเพียงหนึ่งจุด" },
  { number: "04", title: "ตรวจและติดตาม Progress", detail: "ให้คนตรวจจากภาพ 360 แล้วเปรียบเทียบผลจริงกับแผน" },
];

export default async function Home() {
  const [health, user] = await Promise.all([getApiHealth(), getCurrentUser()]);

  return (
    <div className="app-frame">
      <AppHeader user={user} />
      <main>
        <section className="hero section-wrap">
          <div className="hero-copy">
            <p className="eyebrow">360° CONSTRUCTION INTELLIGENCE</p>
            <h1>ตรวจความก้าวหน้าหน้างานจากหลักฐานที่ย้อนกลับไปดูได้</h1>
            <p className="hero-description">
              เชื่อมวิดีโอ Insta360 แบบแปลน BIM และแผนงาน ให้ทีมตรวจงานโครงสร้างจากหลักฐานเดียวกัน
              พร้อมดูงานคงเหลือและ Productivity เทียบกับแผนตามแต่ละวัน
            </p>
            <div className="hero-actions">
              <Link className="button button-primary" href={user ? "/projects" : "/login"}>
                {user ? "เปิดพื้นที่โครงการ" : "เริ่มตั้งค่าระบบ"}
              </Link>
            </div>
          </div>

          <div className="plan-preview" aria-label="ตัวอย่างแผนผังคานชั้นหนึ่ง">
            <div className="preview-toolbar">
              <span>ชั้น 1 · งานคานคอดิน</span>
              <span className={`status-dot ${health.ok ? "is-online" : "is-offline"}`}>
                {health.ok ? "API พร้อม" : "API ยังไม่เปิด"}
              </span>
            </div>
            <div className="grid-plan">
              <span className="grid-label label-a">A</span>
              <span className="grid-label label-b">B</span>
              <span className="grid-label label-c">C</span>
              <span className="grid-label label-1">1</span>
              <span className="grid-label label-3">3</span>
              <span className="grid-label label-6">6</span>
              <div className="beam beam-one" />
              <div className="beam beam-two" />
              <div className="beam beam-three" />
              <div className="beam beam-four" />
              <div className="capture-path" />
              <span className="capture-point point-one" />
              <span className="capture-point point-two" />
              <span className="capture-point point-three" />
            </div>
            <div className="preview-metrics">
              <div><span>Planned</span><strong>—</strong></div>
              <div><span>Human Actual</span><strong>—</strong></div>
              <div><span>Coverage</span><strong>—</strong></div>
            </div>
          </div>
        </section>

        <section className="workflow-section section-wrap">
          <div className="section-heading">
            <div>
              <p className="eyebrow">CORE WORKFLOW</p>
              <h2>จากภาพหน้างานสู่ผลความก้าวหน้าในเส้นทางเดียว</h2>
            </div>
            <p>ขอบเขตปัจจุบันครอบคลุมงานโครงสร้างทุกชั้น และให้คนในโครงการเป็นผู้ยืนยันผล</p>
          </div>
          <div className="step-grid">
            {setupSteps.map((step) => (
              <article className="step-card" key={step.number}>
                <span>{step.number}</span>
                <h3>{step.title}</h3>
                <p>{step.detail}</p>
              </article>
            ))}
          </div>
        </section>
      </main>
    </div>
  );
}
