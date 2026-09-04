# Week 2 Progress — Schedule and Human Actual

> **Scope v2:** การอ้างถึง AI Actual เป็นสถานะการพัฒนาเดิมและไม่ใช่ขอบเขตปัจจุบัน

วันที่อัปเดต: 21 สิงหาคม 2026

## Decision

- Excel/MS Project เป็นแหล่งข้อมูลแผน (`Planned`) เท่านั้น
- `Percent_Complete` ในไฟล์ไม่ถูกนำเข้า และ Preview ต้องแสดงคำเตือน
- `Human Actual` 0–100% กรอกบนเว็บราย Activity และวันที่สังเกต
- Human Actual, AI Actual และ Verified Actual เป็นคนละแหล่งข้อมูล
- การกรอก Human Actual เป็น Append-only: การแก้ไขสร้าง Record ใหม่ ไม่เขียนทับประวัติ

## Completed

- Schedule `.xlsx` Preview API พร้อมตรวจ Header, วันที่, WBS ซ้ำ, Checksum และ Warning
- Schedule Confirm Import API พร้อมเก็บไฟล์ต้นทางใน Object Storage และสร้าง Schedule Version/Activities
- Human Actual Create/List API พร้อม Role และ Project isolation
- Database migration `1d8a918059e3` สำหรับ `human_progress_entries`
- หน้า `/projects/[projectId]/schedule` สำหรับ Preview, Confirm Import และกรอก Human Actual
- หน้า Project list เปิดเข้า Schedule workspace ได้
- Multipart Upload API สำหรับ MP4 สูงสุด 10 GB แบ่ง Part ละ 16 MiB
- Resume API ตรวจ Part ที่อยู่ใน MinIO แล้วและออก Signed URL ใหม่เฉพาะส่วนที่ขาด
- Upload Complete ตรวจขนาด Object ก่อนเปลี่ยน Media เป็น READY และสร้าง Processing Job แบบ Idempotent
- หน้า `/projects/[projectId]/captures` สำหรับเพิ่มชั้น เลือกวิดีโอ เลือกชั้น และคลิกจุดเริ่มต้นบนแบบ
- Web uploader ส่งพร้อมกัน 3 Parts, Retry แต่ละ Part 3 ครั้ง และ Resume จาก Server state
- Database migration `676a09544382` สำหรับ `multipart_upload_sessions`
- Background worker ตรวจวิดีโอด้วย ffprobe และปฏิเสธไฟล์ที่ไม่ใช่ Equirectangular 2:1
- สร้าง Proxy 1920×960, Keyframe ทุก 10 วินาที และ Evidence Media records แบบ Idempotent
- หน้า 360 Viewer เล่นวิดีโอแบบต่อเนื่องบน Sphere, หมุน/ซูม, เลื่อน Timeline และเลือก Keyframe เพื่อกระโดดไป Timestamp ได้
- Processing status รีเฟรชอัตโนมัติและ Retry Job ที่ล้มเหลวได้
- Dashboard คำนวณ Planned ณ Capture Date และเทียบ Human Actual รายกิจกรรม
- Database migration `87a7c87dbddb` สำหรับ `video_metadata` และ `keyframes`
- Acceptance Criteria, SRS, User Flow, Wireframe, ER Diagram และ Data Mapping ตรงกับ Decision ล่าสุด

## Verification

| Check | Result |
|---|---|
| Backend tests | 9 passed |
| Ruff | passed |
| Web ESLint | passed |
| Web TypeScript | passed |
| Next.js production build | passed |
| MinIO multipart integration | 5 MiB + 1 KiB parts completed; object size verified |
| PostgreSQL migration | `676a09544382 (head)` |
| Generated 2:1 video pipeline smoke test | passed |
| Real 8K video `681228` | 1.33 GB, 7680×3840, 81.5 s, 9 keyframes, passed |
| PostgreSQL final migration | `87a7c87dbddb (head)` |
| API live health | `ok` |
| Web login HTTP | `200` |
| Alembic schema drift | none |

## Remaining Week 2

1. Project setup สำหรับ Floor/Room และ Upload แบบบน UI
2. Activity-to-Tracker/Beam Segment Mapping
3. Activity-to-Tracker/Beam Segment Mapping สำหรับ AI Week 3
4. AI Actual และ Verified Actual ซึ่งเป็นขอบเขต Week 3 เป็นต้นไป

Week 2 Engineering Gate ผ่านเส้นทาง `Upload → Process → Keyframes → Viewer → Evidence record` แล้ว โดย Backend Pipeline ทดสอบกับวิดีโอจริง 8K และ Web Viewer ผ่าน Production Build การตรวจหน้าจอเชิงภาพด้วย Browser ยังต้องทำเมื่อ Browser automation พร้อมใช้งาน
