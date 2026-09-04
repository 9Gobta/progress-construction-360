# Localization Baseline v2 Status

> **Scope v2:** Localization AI/CV ยังคงใช้งาน แต่ไม่เชื่อมผล AI Progress; Dashboard ใช้ผลตรวจจริงโดยผู้ใช้

วันที่อัปเดต: 21 สิงหาคม 2569

## ผลที่ทำเสร็จในรอบนี้

- แยก Dense Capture Path ออกจาก Warp Point ในฐานข้อมูลและ API
- เก็บ Capture Path ที่ 1 sample/วินาที ดึงภาพนิ่ง 360 ที่ 2 ภาพ/วินาที และคัดภาพคุณภาพดีที่สุดทุกช่วง 5 วินาทีเป็น Warp Point
- แสดง Capture Path เป็นเส้นสีเขียวและ Warp Point เป็นจุดสีน้ำเงินบนแปลน
- แสดงตำแหน่งกล้องปัจจุบันบนเส้นทางตามเวลาของวิดีโอ
- เพิ่ม Quality Gate แยก `USABLE`, `BLURRY` และ `REJECTED`; เฉพาะ `USABLE` แสดงเป็น Warp Point
- เมื่อ Reviewer ย้าย Warp Point ระบบปรับ Dense Path รอบจุดนั้นแบบต่อเนื่องภายในช่วง ±30 วินาที
- เพิ่ม Two-point Plan Calibration: ผู้ตรวจระบุตำแหน่งจริงของภาพสองเวลา ระบบใช้ Similarity Transform หมุน ปรับสเกล และเลื่อน Path/Camera Poses ทั้งชั้นให้ตรงแบบ
- เพิ่ม migration `d534f86c60ad` และอัปเกรดฐานข้อมูลพัฒนาแล้ว
- ประมวลผล Capture `ac3c0eca-b763-4fcf-b348-d30348e895f0` ด้วย `vo-orb-boundary-v2` สำเร็จ
- ผล Capture จริง: Dense Path 91 จุดช่วง 0–90 วินาที ภาพนิ่ง 360 จำนวน 182 ภาพ และ Warp Point 19 จุด

## ผลตรวจสอบ

- Python lint ผ่าน
- API tests 16 tests ผ่านทั้งหมด
- Web lint ผ่าน
- TypeScript typecheck ผ่าน
- Next.js production build ผ่าน
- Alembic schema check ผ่าน
- API readiness ผ่าน

## ข้อจำกัดที่ยังต้องแก้

เส้นทาง v2 ยังเป็น Visual-Odometry baseline และใช้เพียงขอบภาพเป็น Map Constraint จึงยังไม่ถือว่าผ่าน Accuracy 80% ตำแหน่งที่คนแก้เป็น Calibration/Ground Truth สำหรับพัฒนาการจับคู่กับ Reference Walk ในรุ่นถัดไป

## งานถัดไปตามลำดับ

1. สร้าง Calibration workflow และชุด Ground Truth อย่างน้อย 20 จุดต่อ Capture จำนวน 3 วัน
2. เพิ่ม Reference-walk image matching เพื่อใช้เส้นทางวันที่ตรวจแล้วช่วยวิดีโอวันใหม่
3. สร้าง Walkable Graph/Wall Mask จากแปลนชั้น 1 เพื่อห้ามเส้นทางทะลุผนัง
4. วัด Localization raw accuracy ก่อนมนุษย์แก้และกำหนด Threshold 80%
5. เพิ่ม Floor Transition สำหรับวิดีโอที่เดินข้ามชั้น
6. เตรียม Dataset และเทรน AI Tracker เหล็กคานคอดิน
7. เชื่อม AI Actual, Human Actual และ Planned Progress ใน Dashboard
8. ทำ Acceptance Test, Experiment และเอกสารผลวิจัย

## Localization Baseline v3: SfM Cubemap

อัปเดตเพิ่มเติมวันที่ 21 สิงหาคม 2569:

- ยกเลิก ORB affine เป็นเส้นทางหลัก เพราะแยกการหมุนออกจากการเคลื่อนที่ไม่ได้และบังคับให้เกิดระยะก้าวทุกวินาที
- เพิ่ม `sfm-cubemap-v1` โดยแตก Panorama เป็น Perspective View ซ้อนกัน 4 ทิศ
- ใช้ SIFT feature matching, geometric verification, 3D triangulation และ bundle adjustment เพื่อหา Camera Pose
- การทดลองกับ Capture จริงลงทะเบียนได้ 69 จาก 72 มุมมอง สร้าง 6,094 จุดสามมิติ และมี reprojection error เฉลี่ยประมาณ 0.42 pixel
- เส้นทางจริงถูก interpolate เป็น 91 จุดช่วง 0–90 วินาที ภาพทั้ง 182 จุดผูกกับตำแหน่ง `sfm-cubemap-v1` และคัดเป็น Warp Point 19 จุด
- หยุด Worker เก่าที่โหลด ORB v1 และเปิด Worker ใหม่เพียงชุดเดียวแล้ว

รูปร่างเส้นทางสัมพัทธ์มาจาก 3D Reconstruction แล้ว แต่ MP4 ที่ Export ไม่มี Gyroscope/GPS/IMU ดังนั้นมุมหมุนสัมบูรณ์บนแปลนยังมีความกำกวมเมื่อมีเพียงจุดเริ่มต้นหนึ่งจุด รุ่นถัดไปต้องใช้ Direction Anchor หรือ Reference Walk ที่ตรวจแล้วเพื่อกำหนด orientation บนแปลนและวัด Accuracy 80%
