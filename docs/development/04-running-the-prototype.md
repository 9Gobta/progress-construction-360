# วิธีเปิดและใช้งานต้นแบบ

## 1. เปิด Infrastructure

เปิด Docker Desktop แล้วรันจากโฟลเดอร์รากของโครงการ:

```powershell
Copy-Item .env.example .env
docker compose --env-file .env -f infra/compose.yaml up -d
```

ถ้ามี `.env` อยู่แล้วไม่ต้อง Copy ทับ ให้ตรวจ `DATABASE_URL`, Redis และ MinIO credentials ให้ตรงกับ Compose

## 2. ติดตั้งและ Migration

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".\apps\api[dev]"
npm install
python -m alembic -c apps/api/alembic.ini upgrade head
```

ต้องติดตั้ง FFmpeg และให้คำสั่ง `ffmpeg`/`ffprobe` อยู่ใน PATH

## 3. เปิดระบบ 3 Terminal

Terminal 1 — API:

```powershell
.\.venv\Scripts\python.exe -m uvicorn progress_api.main:app --app-dir apps/api/src --reload
```

Terminal 2 — Background Worker:

```powershell
.\.venv\Scripts\python.exe -m celery -A progress_api.worker:celery_app worker -Q video_cpu --pool=solo --concurrency=1 --loglevel=INFO
```

Terminal 3 — Web:

```powershell
npm run dev:web
```

เปิด `http://localhost:3000`

## 4. ลำดับใช้งาน

1. สมัครบัญชีและสร้างโครงการ
2. เปิดหน้า `แผนงานและ Progress`
3. เลือก Excel แล้วกด Preview และยืนยัน Import
4. เพิ่ม Human Actual 0–100% รายกิจกรรมบนหน้าเดียวกัน
5. เปิดหน้า `Captures` และเพิ่มชั้นถ้ายังไม่มี
6. เลือก MP4 หรือ INSV, วันที่ถ่าย, ชั้นเริ่มต้น และคลิกจุดเริ่มต้นบนแบบ
7. กด Upload; หากหลุดให้เลือกไฟล์เดิมแล้วกด Resume
8. เปิด Capture Viewer เพื่อติดตาม Job; หน้ารีเฟรชสถานะอัตโนมัติทุก 5 วินาที
9. เมื่อ Job สำเร็จ เลือก Keyframe แล้วลากภาพ 360 หรือ Scroll เพื่อซูม
10. เปิด Dashboard เพื่อเลือก Capture Date และดู Planned เทียบ Human Actual

## 5. การแก้ปัญหา

- Job ค้าง `QUEUED`: ตรวจว่า Redis และ Celery worker เปิดอยู่
- Windows แสดง `PermissionError: [WinError 5]` จาก `SpawnPoolWorker`: ปิด Worker ด้วย `Ctrl+C` แล้วเปิดใหม่ด้วย `--pool=solo --concurrency=1`
- Job `FAILED`: เปิด Viewer อ่าน Error แล้วกด `Retry Processing`
- Upload หลุด: ห้ามเปลี่ยนชื่อไฟล์ เลือกไฟล์เดิมและกด Resume
- MP4 ถูกปฏิเสธ: ต้องเป็น Equirectangular อัตราส่วนประมาณ 2:1
- INSV ขึ้น `STITCHER_REQUIRED`: ไฟล์ถูกเก็บแล้ว แต่ Worker ยังไม่ได้ตั้งค่า `INSTA360_STITCHER_PATH`; ติดตั้ง MediaSDK wrapper แล้วกด Retry Processing
- Viewer ไม่มีภาพ: รอ Job เป็น `SUCCEEDED` และตรวจ MinIO ที่พอร์ต 9000
