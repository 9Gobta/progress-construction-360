# Holdout Localization Baseline

> **Scope v2:** เกณฑ์ Holdout ของ Localization ยังคงใช้ ส่วนผล AI Progress ที่อ้างถึงเป็นข้อมูลทดลองเดิม ไม่ใช่ Acceptance Gate และไม่ถูกใช้เป็น Actual

บันทึกผลก่อนปรับระบบเลือก Capture อ้างอิง วันที่ 23 สิงหาคม 2569

| Capture | Dataset split | Ground Truth | ผ่าน tolerance 3% | Accuracy | Mean error |
|---|---|---:|---:|---:|---:|
| 681228 | HOLDOUT_TEST | 20 จุด | 2 จุด | 10% | 0.3742 |
| 690112 | HOLDOUT_TEST | 20 จุด | 2 จุด | 10% | 0.2246 |
| รวม | HOLDOUT_TEST | 40 จุด | 4 จุด | 10% | 0.2994 |

กติกา: ห้ามใช้พิกัด Ground Truth ของสอง Capture นี้ปรับ Scale, Rotation,
Mirror, Translation หรือเลือกค่าพารามิเตอร์ของโมเดล ผลรอบถัดไปต้องเกิดจากข้อมูล
`DEVELOPMENT` เท่านั้น

## Final frozen run

ระบบรุ่น `stella-vslam-visual-graph-v1` เพิ่มการเลือก Capture อ้างอิงจากผลของ
ชุดพัฒนา และใช้ RANSAC Affine รองรับ Scale X/Y, Rotation และ Reflection โดยไม่ใช้
พิกัด Ground Truth ของชุดทดสอบเป็นอินพุต

| Capture | Ground Truth | ผ่าน tolerance 3% | Accuracy | Mean error |
|---|---:|---:|---:|---:|
| 681228 | 20 จุด | 8 จุด | 40% | 0.0408 |
| 690112 | 20 จุด | 20 จุด | 100% | 0.0106 |
| รวม | 40 จุด | 28 จุด | 70% | 0.0257 |

ผลรวมดีขึ้นจาก Baseline 10% เป็น 70% แต่ยังไม่ผ่าน Acceptance Criteria 80%
ช่วงคานเสร็จผ่านแล้ว ส่วนช่วงกำลังก่อสร้างยังต้องเพิ่มชุดพัฒนาก่อนวันที่ 681228
หรือใช้โมเดลแก้ Drift แบบแบ่งช่วงแทน Affine ก้อนเดียว การพัฒนารอบต่อไปห้ามวนปรับ
จากผล Holdout สองวันนี้ และต้องสงวน Capture วันใหม่เป็น Final Holdout

## Piecewise Drift Correction

พัฒนาแล้วหลังตรึงผล Final ข้างต้น ระบบจะใช้เฉพาะภาพจับคู่กับ Capture ในชุด
`DEVELOPMENT` เพื่อสร้าง Drift Anchor อย่างน้อย 3 จุด จากนั้น interpolate ค่าชดเชย
ตามเวลาโดยตรึงจุดเริ่มต้นไว้ ค่าชดเชยแต่ละ Anchor ถูกจำกัดไม่เกิน 15% ของแปลน
และใช้ RANSAC Affine กรองคู่ภาพผิดก่อนเสมอ

ชุดพัฒนาทั้ง 4 วันมี Ground Truth Anchor Accuracy 100% หลังฝึก Piecewise แต่ตัวเลขนี้
เป็น training accuracy ไม่ใช่ผลทดสอบ ห้ามนำไปรายงานเป็นความแม่นยำ Final ระบบรุ่นนี้
ต้องวัดด้วย Capture `HOLDOUT_TEST` วันใหม่ที่ไม่เคยใช้พัฒนามาก่อน

## Independent holdout after Piecewise Drift Correction

บันทึกผลวันที่ 23 สิงหาคม 2569 หลังผู้ประเมินระบุตำแหน่งจริงครบ 20 จุด โดยไม่ใช้
Ground Truth ของ Capture นี้ปรับเส้นทางหรือพารามิเตอร์ของ AI

| Capture | Dataset split | Ground Truth | ผ่าน tolerance 3% | Accuracy | Mean error | RMSE | Max error |
|---|---|---:|---:|---:|---:|---:|---:|
| 690110 | HOLDOUT_TEST | 20 จุด | 13 จุด | 65.0% | 0.0256 | 0.0301 | 0.0662 |

ผลยังไม่ผ่าน Acceptance Criteria 80% โดยมี 7 จุดที่คลาดเคลื่อนเกิน 3% ของขนาดแปลน
ความคลาดเคลื่อนสูงสุดอยู่ที่เวลา 02:20.5 (6.62% ของขนาดแปลน) จุดที่ไม่ผ่านอยู่ที่
00:09.5, 00:16.5, 00:24.5, 00:47.5, 02:20.5, 02:32.0 และ 03:41.0 จุดเหล่านี้ใช้ทำ
Error Analysis เท่านั้น ห้ามนำพิกัด Ground Truth ของ Capture `690110` กลับไปฝึกหรือ
เลือกพารามิเตอร์

## Final independent holdout — Vision Graph v2

บันทึกผลวันที่ 23 สิงหาคม 2569 จาก Capture `690111` ซึ่งกำหนดเป็น `HOLDOUT_TEST`
ก่อนประมวลผล และไม่เคยถูกใช้พัฒนา ปรับพารามิเตอร์ หรือเลือก Reference Walk มาก่อน
ระบบรุ่น `stella-vslam-visual-graph-v2` เลือก Capture ชุดพัฒนา `690105` เป็น Reference
จาก Visual Match โดยไม่อ่าน Ground Truth ของชุดทดสอบ

| Capture | Algorithm | Ground Truth | ผ่าน tolerance 3% | Accuracy | Mean error | RMSE | Max error |
|---|---|---:|---:|---:|---:|---:|---:|
| 690111 | stella-vslam-visual-graph-v2 | 20 จุด | 18 จุด | 90.0% | 0.0153 | 0.0180 | 0.0346 |

ผลผ่าน Acceptance Criteria ที่กำหนด Localization Accuracy อย่างน้อย 80% จุดที่ไม่ผ่าน
อยู่ที่เวลา 02:26.5 และ 02:43.0 โดยคลาดเคลื่อน 3.22% และ 3.46% ของขนาดแปลนตามลำดับ
Capture นี้ถูกตรึงเป็น Final Holdout ห้ามกดคำนวณ AI ใหม่ แก้แนว หรือใช้ Ground Truth
ย้อนกลับไปปรับระบบ

> ผล Holdout ของ AI Progress คานแยกบันทึกไว้ที่
> `docs/development/08-beam-progress-ai-baseline.md` เพื่อไม่ให้สับสนกับ Accuracy
> ของ Localization
