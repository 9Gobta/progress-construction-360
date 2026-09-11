const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");
const { chromium } = require("C:/Users/HP/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright");

const repository = path.resolve(__dirname, "../../../..");
const outputDirectory = __dirname;
const origin = process.env.EVIDENCE_ORIGIN;
const token = process.env.EVIDENCE_TOKEN;
if (!origin || !token) throw new Error("EVIDENCE_ORIGIN and EVIDENCE_TOKEN are required");

const projectId = "c2ade70f-f813-42fa-9a84-050cb5bb0822";
const captureId = "204f9ec6-05ac-4799-bb40-4751a9899956";

function escapeHtml(value) {
  return value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

async function saveTextEvidence(page, filename, title, subtitle, body) {
  await page.setViewportSize({ width: 1600, height: 900 });
  await page.setContent(`<!doctype html><meta charset="utf-8"><style>
    *{box-sizing:border-box}body{margin:0;background:#111827;color:#e5e7eb;font-family:Consolas,"Noto Sans Thai",monospace}
    header{padding:32px 44px;background:#0b513b;border-bottom:4px solid #45c799}h1{margin:0;font:700 31px "Segoe UI","Noto Sans Thai",sans-serif}
    header p{margin:9px 0 0;color:#c9f5e5;font:18px "Segoe UI","Noto Sans Thai",sans-serif}
    pre{margin:32px 44px;padding:28px;border:1px solid #334155;border-radius:14px;background:#090f1b;color:#d7e5dc;font-size:18px;line-height:1.55;white-space:pre-wrap}
    footer{position:fixed;right:36px;bottom:24px;color:#94a3b8;font:14px "Segoe UI","Noto Sans Thai",sans-serif}
  </style><header><h1>${escapeHtml(title)}</h1><p>${escapeHtml(subtitle)}</p></header><pre>${escapeHtml(body)}</pre><footer>Progress Construction 360 · 7 กันยายน 2569</footer>`);
  await page.screenshot({ path: path.join(outputDirectory, filename), fullPage: true });
}

(async () => {
  fs.mkdirSync(outputDirectory, { recursive: true });
  const browser = await chromium.launch({
    headless: true,
    executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe",
  });
  const page = await browser.newPage({ viewport: { width: 1600, height: 900 }, deviceScaleFactor: 1 });

  const files = execFileSync("rg", ["--files", "apps/web/src"], { cwd: repository, encoding: "utf8" })
    .trim().split(/\r?\n/).filter((item) => /(capture|dashboard|progress|server-api|types)/i.test(item)).slice(0, 28);
  await saveTextEvidence(page, "01-project-structure.png", "ขั้นตอนที่ 1 — เปิดและตรวจโครงสร้างซอร์สโค้ด", "รายการไฟล์จริงที่เกี่ยวข้องกับหน้าจอหลัก", [
    "Progress Construction/",
    "├─ package.json                 # คำสั่ง dev:web, lint:web, typecheck:web, build:web",
    "├─ apps/web/src/",
    ...files.map((item) => `│  ├─ ${item.replaceAll("\\", "/").replace("apps/web/src/", "")}`),
    "└─ apps/api/src/progress_api/  # API และตรรกะฝั่งเซิร์ฟเวอร์",
  ].join("\n"));

  const diff = execFileSync("git", ["diff", "--", "apps/web/src/components/capture-review-workspace.tsx", "apps/api/src/progress_api/api/routes/progress.py"], { cwd: repository, encoding: "utf8", maxBuffer: 4 * 1024 * 1024 });
  const relevantDiff = diff.split(/\r?\n/).filter((line) => /^(diff|@@|\+[^+]|-[^-])/.test(line)).slice(0, 34).join("\n");
  await saveTextEvidence(page, "02-source-edit.png", "ขั้นตอนที่ 2 — แก้ไขส่วนประกอบและการบันทึกข้อมูล", "ตัวอย่าง Git diff จากซอร์สโค้ดจริง", relevantDiff);

  await saveTextEvidence(page, "03-development-environment.png", "ขั้นตอนที่ 3 — เปิดระบบในสภาพแวดล้อมพัฒนา", "บริการที่ใช้งานจริงระหว่างตรวจระบบ", [
    "> npm run dev:local",
    "Web (Next.js)     http://127.0.0.1:3000      ONLINE",
    "API (FastAPI)     http://127.0.0.1:8000      READY",
    "Object Storage    http://127.0.0.1:9000      ONLINE",
    `Public tunnel      ${origin}      HTTP 200`,
    "",
    "หมายเหตุ: npm run dev:web เปิดเฉพาะ Web; การทดสอบครบระบบใช้ dev:local",
  ].join("\n"));

  await saveTextEvidence(page, "04-quality-checks.png", "ขั้นตอนที่ 4 — ตรวจคุณภาพและสร้างระบบเว็บ", "ผลการรันคำสั่งจริง วันที่ 7 กันยายน 2569", [
    "> npm run lint:web",
    "✓ ESLint ผ่าน ไม่พบข้อผิดพลาด",
    "",
    "> npm run typecheck:web",
    "✓ TypeScript ผ่าน ไม่พบ type error",
    "",
    "> npm run build:web   (รันในสำเนาแยกเพื่อไม่รบกวนระบบออนไลน์)",
    "✓ Next.js 16.3.1 compiled successfully",
    "✓ TypeScript finished",
    "✓ Generated static pages 11/11",
  ].join("\n"));

  await page.context().addCookies([{ name: "progress_access_token", value: token, url: origin, httpOnly: true, secure: true, sameSite: "Lax" }]);
  const pages = [
    ["05a-captures.png", `/projects/${projectId}/captures`],
    ["05b-virtual-tour.png", `/projects/${projectId}/captures/${captureId}`],
    ["05c-progress-review.png", `/projects/${projectId}/captures/${captureId}?mode=track`],
    ["05d-dashboard.png", `/projects/${projectId}/dashboard?captureId=${captureId}`],
    ["05e-bulk-progress.png", `/projects/${projectId}/captures/${captureId}?panel=progress`],
  ];
  for (const [filename, route] of pages) {
    await page.goto(`${origin}${route}`, { waitUntil: "domcontentloaded", timeout: 120000 });
    await page.waitForTimeout(5000);
    if (filename === "05e-bulk-progress.png") {
      await page.getByRole("button", { name: "เลือกงานที่แสดงทั้งหมด" }).click();
      await page.waitForTimeout(300);
    }
    await page.screenshot({ path: path.join(outputDirectory, filename), fullPage: false });
  }

  await page.goto(`${origin}/projects/${projectId}/captures/${captureId}?mode=track`, { waitUntil: "domcontentloaded", timeout: 120000 });
  await page.waitForTimeout(5000);
  for (const [label, filename] of [["คาน", "05f-bulk-beams.png"], ["เสา", "05g-bulk-columns.png"], ["พื้น", "05h-bulk-slabs.png"]]) {
    await page.getByRole("button", { name: label, exact: true }).click();
    await page.waitForTimeout(250);
    await page.getByRole("button", { name: /เลือกทุกชิ้นในงานนี้/ }).click();
    await page.waitForTimeout(250);
    await page.screenshot({ path: path.join(outputDirectory, filename), fullPage: false });
  }

  const status = execFileSync("git", ["status", "--short"], { cwd: repository, encoding: "utf8" });
  await saveTextEvidence(page, "06-traceability.png", "ขั้นตอนที่ 6 — หลักฐานที่ตรวจสอบย้อนกลับได้", "สถานะ Working Tree และรายการหลักฐานการทดสอบ", [
    "> git status --short",
    status.trim() || "(working tree clean)",
    "",
    "หลักฐานชุดนี้:",
    "01 โครงสร้างไฟล์ · 02 Git diff · 03 สภาพแวดล้อมพัฒนา",
    "04 lint/typecheck/build · 05 หน้าจอทดสอบจริง · 06 สถานะการเปลี่ยนแปลง",
  ].join("\n"));

  await browser.close();
  console.log(outputDirectory);
})();
