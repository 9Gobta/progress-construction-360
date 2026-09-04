# Beam Progress AI Baseline

> **สถานะ: Archived.** เก็บผลทดลองเดิมเพื่ออ้างอิงเท่านั้น ระบบปัจจุบันไม่รัน ไม่ประเมิน และไม่แสดง AI Progress เป็น Actual

บันทึกวันที่ 24 สิงหาคม 2569

## ขอบเขต

- งานทดลอง: เหล็กคานคอดินชั้น 1 จำนวน 10 Beam Segments
- รุ่นโมเดล: `beam-visual-temporal-v1`
- ชุดพัฒนา: `681223`, `681226`, `690105`, `690109`
- ชุดทดสอบที่ห้ามใช้ปรับโมเดล: `681228`, `690112`
- ผลทำนายถูกเก็บแยกจาก Human Ground Truth และมี model version, dataset
  fingerprint, evidence keyframe และ confidence

## วิธีทำงานของ Baseline

1. เลือกภาพหลักฐานของแต่ละ Segment จากภาพที่ผู้ตรวจผูกไว้ หรือภาพที่มี Camera Pose
   ใกล้จุดกึ่งกลาง Segment ที่สุด
2. สกัด visual descriptor จากสี ความคม ขอบ และ texture ของภาพ 360
3. ใช้ visual distance ตรวจความใหม่/ความน่าเชื่อถือของหลักฐาน
4. ใช้ monotonic temporal regression จาก Human Ground Truth เฉพาะวันพัฒนาเพื่อทำนาย
   Progress 0–100%
5. Confidence ต่ำถูกส่งเป็น `NEEDS_REVIEW`; ไม่มีภาพที่มีตำแหน่งเป็น `NOT_VISIBLE`

โมเดลนี้เป็น Hybrid Baseline สำหรับข้อมูลเพียง 4 วัน ยังไม่ใช่ Transfer Learning
Classifier ตามแบบสุดท้าย เมื่อมีภาพ Crop/มุมมองคานและป้ายกำกับมากขึ้น ต้องเปลี่ยนเป็น
ResNet18/EfficientNet-B0 และเปรียบเทียบกับ Baseline นี้ด้วย Validation เดิม

## Development validation

ใช้ Leave-One-Capture-Date-Out เพื่อป้องกันภาพจากวันเดียวกันรั่วข้าม Train/Validation

| วันที่ที่เว้นออก | MAE (percentage points) |
|---|---:|
| 681223 | 12.35 |
| 681226 | 17.70 |
| 690105 | 11.42 |
| 690109 | 13.71 |
| รวม 40 Segment-Date | 13.79 |

ค่า MAE รวมผ่านเกณฑ์ Development ที่ไม่เกิน 15 จุดเปอร์เซ็นต์ แต่ผลวันที่ `681226`
ยังเกินเกณฑ์ จึงต้องรายงานทั้งผลรวมและผลรายวัน ห้ามสรุปว่าโมเดลแม่น 80% จากผลนี้

## Frozen blind predictions

ผลด้านล่างสร้างหลังตรึง `beam-visual-temporal-v1` และก่อนกรอก Ground Truth ชุดทดสอบ

| Capture | AI Actual เฉลี่ย | Mean confidence | Segment ที่ทำนายได้ |
|---|---:|---:|---:|
| 681228 | 23.02% | 63.8% | 10/10 |
| 690112 | 88.13% | 66.5% | 10/10 |

ตัวเลขนี้เป็น prediction ไม่ใช่ accuracy ขั้นต่อไปคือให้ผู้ตรวจกรอก Ground Truth ของ
สองวันโดยห้ามกดวิเคราะห์ AI ซ้ำ แล้วระบบจึงคำนวณ MAE และ Installed/Not Installed F1
เพื่อพิจารณา Acceptance Criteria

## Final holdout evaluation

ผู้ตรวจกรอก Ground Truth หลัง Prediction ถูกตรึงแล้ว โดยไม่ได้วิเคราะห์ AI ซ้ำ

| Capture | Human Actual | AI Actual | MAE | ภายใน 15 pp | Installed F1 |
|---|---:|---:|---:|---:|---:|
| 681228 | 40.00% | 23.02% | 16.98 pp | 50.0% | 0.000 |
| 690112 | 100.00% | 88.13% | 11.87 pp | 80.0% | 1.000 |
| รวม 20 Segment-Date | — | — | **14.426 pp** | **65.0%** | **0.667** |

สรุปตาม Acceptance Criteria:

- `AC-AI-01` ผ่าน: ทุก Segment มี Prediction, Status และ Confidence
- `AC-AI-03/04` ผ่าน: Coverage 10/10 ต่อ Capture และ Actual ถ่วงน้ำหนักด้วยความยาว
- `AC-AI-05` ยังไม่ผ่าน Target: F1 0.667 ต่ำกว่า 0.75
- `AC-AI-06` ผ่าน: MAE 14.426 ไม่เกิน 15 percentage points
- `AC-AI-08` ผ่าน: ผลผูกกับ Model Version, Dataset Fingerprint และ Capture

ห้ามนำผลผิดพลาดของ `681228` หรือ `690112` กลับไปปรับ threshold/weights ของรุ่นนี้
การปรับปรุงรอบต่อไปต้องเพิ่มภาพ Crop ที่หันเข้าหา Beam Segment และ Label จาก Capture
ชุดพัฒนาใหม่ จากนั้นตรึงโมเดลใหม่และใช้ Capture วันใหม่เป็น Final Holdout
