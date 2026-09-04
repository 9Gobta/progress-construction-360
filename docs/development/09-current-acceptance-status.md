# Current Acceptance Status

> **Scope v2:** ค่า Actual มาจากผู้ตรวจเท่านั้น AI/CV ใช้เฉพาะ Localization
> ตาราง AI Progress ตอนท้ายเป็นผลประวัติ Baseline 1.0 และไม่นับเป็นเกณฑ์ผ่านปัจจุบัน

อัปเดตวันที่ 2 กันยายน 2569

## สถานะปัจจุบันตาม Scope v2

| หมวด | ผลล่าสุด | สถานะ |
|---|---:|---|
| Localization | Accuracy 90.0% บน Final Holdout `690111` | ผ่าน |
| Human Progress UI | คาน เสา พื้น งานโครงสร้างหลังคา และ Dashboard ใช้ผลตรวจโดยผู้ใช้ | ผ่าน |
| No Progress AI | ไม่มีปุ่ม/route AI ใน Web; Backend legacy run/evaluation ตอบ `410 Gone` | ผ่าน |
| Structural inventory | 618 องค์ประกอบที่ Active | ผ่าน |
| Beam geometry | 219 คาน มีความยาวครบ รวม 662.850 ม. | รอตรวจมือ |
| Slab geometry | 115 พื้น มีพื้นที่ครบ รวม 800.634 ตร.ม. | รอตรวจมือ |
| Capture processing | 211 Capture: READY 36, REVIEW_REQUIRED 174, FAILED 1 | มีข้อจำกัด |
| Quality checks | Web lint/typecheck/build, API tests และ Alembic check | ผ่าน |

## งานที่ยังต้องใช้ผู้ตรวจ

1. ตรวจความยาวคานและพื้นที่พื้นเทียบแบบจริงด้วยมือก่อนนำไปสรุป Progress
2. ตรวจ Capture ที่เป็น `REVIEW_REQUIRED` ตามหลักฐานหน้างาน ไม่ถือว่าเป็นความล้มเหลวอัตโนมัติ
3. Capture ที่ Failed หนึ่งรายการต้องมีไฟล์ต้นทางที่ถูกต้องก่อน Retry

## ผล AI Progress เดิม (Archived Baseline 1.0)

| หมวด | เกณฑ์ | ผลล่าสุด | สถานะ |
|---|---|---:|---|
| Localization | Accuracy อย่างน้อย 80% | 90.0% บน Final Holdout `690111` | ผ่าน |
| AI Progress | ทุก Segment มีสถานะและ Confidence | 20/20 Segment | ผ่าน |
| AI Progress | Length-weighted Actual | 10/10 Segment ต่อ Capture | ผ่าน |
| AI Progress | MAE ไม่เกิน 15 pp | 14.426 pp | ผ่าน |
| AI Progress | Installed F1 อย่างน้อย 0.75 | 0.667 | ยังไม่ผ่าน |
| Reproducibility | Model/Capture/Dataset fingerprint | `beam-visual-temporal-v1` | ผ่าน |
| Planned vs Actual | คำนวณ ณ Capture Date | เชื่อม Baseline Schedule แล้ว | ผ่าน |

## ข้อจำกัดที่ต้องรายงาน

1. AI Progress ใช้ชุดพัฒนาเพียง 4 Capture Dates รวม 40 Segment-Date
2. วันที่ `681228` เป็น Error Case หลัก: Human 40% แต่ AI เฉลี่ย 23.02%
3. ห้ามปรับโมเดลจากข้อผิดพลาดของ `681228`/`690112` เพราะเป็น Holdout
4. ต้องเพิ่ม Capture ชุดพัฒนาช่วงก่อนและระหว่างติดตั้งเหล็ก เช่น `681225` และวันใกล้เคียง
5. หลังเพิ่มข้อมูลให้ตรึงโมเดลรุ่นใหม่ และใช้ Capture วันใหม่ที่ไม่เคยเห็นเป็น Final Holdout

## การแปลง Progress เข้ากิจกรรมแผน

Progress หน้างานใช้ Milestone รวมของคาน ส่วน Dashboard แปลงเป็นกิจกรรมดังนี้:

| Overall milestone | กิจกรรมใน Schedule | Activity progress |
|---:|---|---:|
| 20–40 | ผูกเหล็กคานคอดิน | 0–100% |
| 40–60 | เข้าแบบคานคอดิน | 0–100% |
| 60–80 | เทคานคอดิน | 0–100% |
| 80–100 | ถอดแบบ/ตรวจผ่าน | 0–100% |

จึงสามารถเปรียบเทียบ Planned, AI Actual และ Human Actual ในหน่วยเดียวกันได้ โดยค่า
Overall 0–100 ยังคงใช้คำนวณ MAE งานวิจัยโดยตรง
