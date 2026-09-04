# Week 1 Foundation — Development Log

| รายการ | ค่า |
|---|---|
| วันที่ | 21 สิงหาคม 2026 |
| สถานะ | In progress |
| Planning baseline | 1.0 |
| Environment | Windows 11, WSL 2.7.12, Docker Desktop 4.87.0, Python 3.10, Node.js 24, RTX 4050 |

## Completed

- สร้าง Git monorepo ตาม System Architecture
- สร้าง Next.js 16 + TypeScript Web application
- สร้าง FastAPI modular API และ OpenAPI documentation
- สร้าง SQLAlchemy models และ Alembic migration ชุดแรก
- รองรับ Register, Login, Current user และ JWT authentication
- Web เก็บ Access token ใน HTTP-only, SameSite cookie ไม่เก็บใน Local Storage
- รองรับ Create/List/Get Project พร้อม Project membership isolation
- ตั้ง Celery + Redis configuration และ smoke task
- ตั้ง Docker Compose สำหรับ PostgreSQL, Redis และ MinIO
- ติดตั้ง Docker Desktop แบบ WSL 2 และย้าย Docker data disk ไป `D:\DockerData`
- เปิด PostgreSQL, Redis และ MinIO พร้อม Health Check และสร้าง bucket `progress-construction`
- เพิ่ม SQLite development fallback เพราะเครื่องยังไม่มี Docker
- สร้าง Dataset Inventory พร้อม SHA-256 และ ffprobe metadata โดยไม่แก้ Source data
- ทดสอบ End-to-end ผ่าน Browser: Login → Project list → Create project
- ตรวจ Excel จริง 26 กิจกรรมและล็อก Import mapping สำหรับ Start/Finish; Percent Complete ไม่นำเข้า
- แปลงแบบ `ST-03` หน้า 3 เป็นภาพ Web พร้อมยืนยัน Grid `1–6` และ `A–D`
- เพิ่ม Core tables: Floor, Room, Sheet, Grid, Beam Segment, Schedule, Activity, Media, Capture และ Processing Job
- เพิ่ม API foundation สำหรับ Floor, Video metadata และ Capture พร้อม Project isolation
- สร้าง Label Handbook v0.1 และ Draft Beam Segment 10 ช่วงสำหรับ Calibration

## Verification evidence

| Check | Result |
|---|---|
| Backend unit/API tests | 8 passed |
| Ruff | Passed |
| Alembic upgrade | `20260821_0001 (head)` |
| Alembic model drift check | No new upgrade operations detected |
| ESLint | Passed |
| TypeScript | Passed |
| Next.js production build | Passed; 7 application routes |
| Browser console errors | 0 |
| E2E Login | Passed |
| E2E Create Project | Passed |
| Dataset manifest | 15 files, 6,938,130,514 bytes, SHA-256 complete |
| Docker Engine / Compose | Engine 29.7.2 / Compose 5.4.0 |
| Compose services | PostgreSQL, Redis และ MinIO healthy |
| PostgreSQL migration | `20260821_0001 (head)`; no schema drift |
| MinIO health / bucket | HTTP 200 / `progress-construction` created |
| Celery + Redis smoke task | Passed; `system_ping` returned `status=ok` |
| Core migration | `05467aeda70a (head)`; no schema drift |
| Schedule source validation | 26 rows; Start/Finish fallback; Percent Complete ignored with warning |
| Structural preview | `ST-03`, 2482×1755 PNG, visual QA passed |
| Draft Beam Segments | 10 segments; all marked `needs_review`, excluded from training |

## Dataset inventory summary

| Kind | Files |
|---|---:|
| Video | 6 |
| Schedule | 3 |
| Drawing/document | 5 |
| BIM | 1 |

MP4 ทั้ง 4 วันอ่านได้ด้วย ffprobe เป็น H.264 ความละเอียด 7680×3840 ส่วน `.insv` อ่านได้เป็น HEVC 3840×3840 แต่ยังไม่ใช่ Core Input

Manifest: `ml/datasets/source-inventory.json`

## Remaining Week 1 work

- ทำหน้า Web ตรวจ/แก้ Grid และ Beam Segment ก่อนอนุมัติ Ground Truth
- ทำ Schedule Import Preview/Validation UI และบันทึก Schedule Version
- ทำ Multipart upload จริงเข้า MinIO พร้อม Resume/Retry
- Localize Keyframe เข้ากับแบบก่อนติด Label Segment รายตัว

## Known limitations

- พื้นที่เก็บข้อมูลยังจำกัด: Docker data อยู่ไดรฟ์ D เพื่อไม่ใช้ไดรฟ์ C แต่ควรเพิ่มพื้นที่ว่างก่อนเริ่มเก็บวิดีโอและโมเดลจำนวนมาก
- Compose ใช้รหัสผ่าน development จาก `.env.example`; ต้องเปลี่ยนเป็น Secret จริงก่อนเปิดให้เครื่องอื่นหรือ Deploy
- Draft Segment 10 ช่วงยังไม่ใช่ Ground Truth เพราะวิดีโอ 4 วันยังไม่มี Start Point/Path ที่ผูกกับ Grid
- ระบบ Web ปัจจุบันครอบคลุม Authentication และ Project foundation; Sheet/Schedule/Capture เริ่มในลำดับถัดไป
- Dev SQLite มีบัญชีและโครงการ E2E ตัวอย่าง ซึ่งถูก Ignore จาก Git และไม่ใช่ข้อมูลวิจัย
