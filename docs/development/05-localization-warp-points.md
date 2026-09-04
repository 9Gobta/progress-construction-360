# Localization and Warp Points Baseline

สถานะ ณ 21 สิงหาคม 2569: Core flow `Upload → Process → Localize → Warp Point → 360 Viewer → Human correction` ทำงานแล้วกับ Capture จริงวันที่ 23 ธันวาคม 2568

## สิ่งที่พัฒนาแล้ว

- ตาราง `camera_poses` เชื่อมหนึ่ง Keyframe กับชั้น พิกัด normalized ทิศกล้อง Confidence และ Localization Run
- Worker `localize_capture` ทำงานเบื้องหลังบนคิว `video_cpu`
- Visual-odometry baseline `vo-orb-boundary-v1`
  - ดึง Tracking Frame 1 FPS จาก MP4 ต้นฉบับ
  - จับ ORB features และ RANSAC affine motion ระหว่างเฟรม
  - ประมาณระยะก้าวและการเปลี่ยนทิศจาก image motion
  - ทดลองทิศเริ่มต้นหลายค่าและเลือกเส้นทางที่ไม่ออกนอกขอบแปลน
  - ผูกตำแหน่งกลับเข้ากับ Timestamp ของ Keyframe
- Split View แสดง Capture Path/Warp Points คู่กับภาพนิ่ง 360
- คลิก Warp Point หรือเส้นทางเพื่อเปิดภาพ 360 ที่สัมพันธ์กับตำแหน่งนั้น โดยไม่เล่นวิดีโอต่อเนื่อง
- จุด Confidence ต่ำมีสถานะ `needs_review`
- Admin/Reviewer ย้ายจุดและเปลี่ยนชั้นได้ ผลแก้ถูกบันทึกแยกด้วย `reviewed_by_id`, `reviewed_at` และ algorithm suffix `+human-review`
- สั่งคำนวณ Localization ใหม่จากหน้า Viewer ได้

## ผลรันกับ Capture จริง

- Capture: `ac3c0eca-b763-4fcf-b348-d30348e895f0`
- Source: Insta360 X5 MP4 8K ขนาดประมาณ 1.49 GB
- ภาพนิ่ง 360: 182 ภาพที่ 2 ภาพ/วินาที; Warp Points: 19 จุด ช่วงเวลา 0–90.5 วินาที
- Processing Job: `72eaa6a2-91e0-4a08-b6d6-107bbde87b09`
- Job status: `SUCCEEDED 100%`
- Confidence: ต่ำสุด 68%, เฉลี่ย 76%, สูงสุด 100%

ค่า Confidence เป็นความมั่นใจภายในของ Algorithm ไม่ใช่ Accuracy 80% ตามเกณฑ์วิจัย การประกาศ Accuracy ต้องสร้าง Ground Truth ตำแหน่งจริงอย่างน้อย 20 จุดต่อ Capture แล้วคำนวณผลก่อนมนุษย์แก้ตาม Acceptance Criteria

## ข้อจำกัดที่ต้องรายงานอย่างตรงไปตรงมา

- Baseline ใช้ขอบสี่เหลี่ยมของภาพเป็น Map Constraint เพราะยังไม่มี Walkable Graph/Wall Mask ที่สกัดจากแบบ
- Scale จากกล้องเดียวมีความกำกวม จึงเป็นตำแหน่งระดับบริเวณ ไม่ใช่ระดับเซนติเมตร
- วิดีโอที่เดินข้ามชั้นยังเริ่มต้นด้วยชั้นที่ผู้ใช้งานระบุ จุดที่เปลี่ยนชั้นต้องให้ Reviewer แก้จนกว่าจะมี Floor-transition model และข้อมูล Ground Truth เพียงพอ
- ขณะนี้ตั้งค่าแบบโครงสร้างชั้น 1 แล้ว ชั้น 2–4 มีรายการชั้นในระบบแต่ยังต้องเพิ่มไฟล์แบบของแต่ละชั้น
- การตรวจหน้าจออัตโนมัติด้วย Browser ยังไม่ได้รัน เพราะไม่มี Browser session เชื่อมต่อในขณะทดสอบ โค้ดผ่าน Production Build และ API integration tests แล้ว

## การตรวจสอบ

```powershell
.\.venv\Scripts\python.exe -m ruff check apps/api/src apps/api/tests
.\.venv\Scripts\python.exe -m pytest apps/api/tests
npm run lint:web
npm run typecheck:web
npm run build:web
```
