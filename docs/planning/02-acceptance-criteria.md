# Acceptance Criteria

> **Scope Amendment v2.0 — 27 สิงหาคม 2026 (ข้อกำหนดปัจจุบัน)**
>
> ยกเลิกหัวข้อ AI Progress, AI-vs-Human, F1, MAE และ Time Saving ด้านล่างซึ่งเก็บไว้เป็น
> ประวัติ Baseline 1.0 ค่า Actual ต้องมาจากผู้ใช้ตรวจภาพ 360 และผูกหลักฐานเท่านั้น
> AI/CV ยังใช้กับ Localization ตามหัวข้อ 4

## ระบบประเมินความก้าวหน้างานก่อสร้างจากวิดีโอ 360 องศา

| รายการ | ค่า |
|---|---|
| สถานะเอกสาร | Approved - Round 1 |
| เวอร์ชัน | 1.0 |
| วันที่ | 21 สิงหาคม 2026 |
| อ้างอิง | SRS Version 1.0 |

## 1. นิยามระดับผลการทดสอบ

- **Pass**: ผลตรงตามเกณฑ์และมีหลักฐานการทดสอบ
- **Pass with Limitation**: ฟังก์ชันหลักทำงาน แต่มีข้อจำกัดที่บันทึกไว้และไม่ทำให้ผลวิจัยผิดความหมาย
- **Fail**: ไม่สามารถทำงานตามกระบวนการหลักหรือให้ผลที่ตรวจสอบย้อนกลับไม่ได้
- **Not Tested**: ยังไม่มีข้อมูลหรือสภาพแวดล้อมสำหรับทดสอบ

การส่งโครงงานถือว่าผ่านเมื่อ Acceptance Criteria ระดับ Must ผ่านทั้งหมด หรือมี Pass with Limitation เฉพาะรายการที่ระบุว่ายอมรับข้อจำกัดได้ โดยต้องไม่มีข้อผิดพลาดที่ทำให้ข้อมูลสูญหายหรือรายงานผลผิดโครงการ/ผิดวันที่

## 2. Core Workflow Acceptance Criteria

| ID | เกณฑ์ทดสอบ | ผลที่ต้องได้ | Priority | SRS |
|---|---|---|---|---|
| AC-CORE-01 | สร้างโครงการใหม่ | ระบบบันทึกชื่อ ที่ตั้ง และเขตเวลา และเปิดหน้าโครงการได้ | Must | FR-PRJ-01,02 |
| AC-CORE-02 | อัปโหลดแบบชั้น 1 | แบบแสดงผล ซูม เลื่อน และคลิกตำแหน่งได้ | Must | FR-SHT-01,02 |
| AC-CORE-03 | กำหนด Scale/Grid | ระบบบันทึก Scale, Grid และ Beam Segment และเปิดซ้ำได้โดยตำแหน่งไม่เปลี่ยน | Must | FR-SHT-03,04 |
| AC-CORE-04 | Import Excel รอบล่าสุด | อ่าน Name, WBS, Start และ Finish ของกิจกรรมคานคอดินได้ถูกต้อง | Must | FR-SCH-01,02 |
| AC-CORE-05 | ตรวจไฟล์ก่อน Import | แสดง Preview และแจ้งแถวที่วันที่หรือ WBS ไม่ถูกต้อง | Must | FR-SCH-03,04 |
| AC-CORE-06 | Schedule Version | Import ไฟล์เดิมหรือไฟล์ใหม่แล้ว Baseline Version 1 ยังอยู่ครบ | Must | FR-SCH-05,06 |
| AC-CORE-07 | Activity Mapping | จับคู่กิจกรรมงานผูกเหล็กคานคอดินกับ Tracker, Floor และ Beam Segment ได้ | Must | FR-MAP-01,02 |
| AC-CORE-08 | Unsupported Activity | กิจกรรมที่ไม่จับคู่แสดง Manual Only/Unsupported และไม่มี AI Actual ปลอม | Must | FR-MAP-03,04 |
| AC-CORE-09 | Ignore Excel Actual | เมื่อไฟล์มี Percent Complete ระบบแจ้งเตือนและไม่บันทึกค่านั้นเป็น Human/AI/Verified Actual | Must | FR-SCH-02, BR-02A |

## 3. Video Upload and Processing

| ID | เกณฑ์ทดสอบ | ผลที่ต้องได้ | Priority | SRS |
|---|---|---|---|---|
| AC-VID-01 | อัปโหลด MP4 360 ขนาดอย่างน้อย 1.2 GB | อัปโหลดสำเร็จ แสดงเปอร์เซ็นต์ และไฟล์ไม่เสีย | Must | FR-CAP-01,02 |
| AC-VID-02 | ตรวจ Metadata | ระบบอ่านความละเอียด ระยะเวลา วันที่ถ่าย และขนาดไฟล์ได้ | Must | FR-CAP-04,05 |
| AC-VID-03 | Background Processing | หลังเริ่มประมวลผล ปิดหน้าเว็บและเปิดใหม่แล้ว Job ยังทำต่อหรือแสดงสถานะเดิม | Must | FR-CAP-06 |
| AC-VID-04 | Processing Status | สถานะเปลี่ยนตามขั้นตอนและแสดง Error ที่เข้าใจได้เมื่อ Job ล้มเหลว | Must | FR-CAP-07 |
| AC-VID-05 | Invalid File | ไฟล์ที่ไม่ใช่วิดีโอหรืออัตราส่วนไม่รองรับถูกปฏิเสธก่อนเข้า AI | Must | FR-CAP-05 |
| AC-VID-06 | Processing Time | MP4 8K ระยะ 81-93 วินาทีประมวลผลครบภายใน 30 นาทีบน RTX 4050 | Target | NFR-PERF-03 |
| AC-VID-07 | Large Resumable Upload | ไฟล์มากกว่า 2 GB สามารถพักและส่งต่อโดยไม่เริ่มใหม่ทั้งหมด | Should | FR-CAP-03 |

## 4. Localization and 360 Viewer

| ID | เกณฑ์ทดสอบ | ผลที่ต้องได้ | Priority | SRS |
|---|---|---|---|---|
| AC-LOC-01 | เลือกจุดเริ่มต้น | ผู้ใช้คลิกชั้นและจุดเริ่มต้นหนึ่งครั้งโดยไม่ต้องระบุทิศหรือวาด Path | Must | FR-LOC-01,02 |
| AC-LOC-02 | สร้าง Capture Path | ระบบสร้างเส้นทางและแสดงบนแบบโดยอัตโนมัติ | Must | FR-LOC-03,05 |
| AC-LOC-03 | Keyframe Mapping | อย่างน้อย 80% ของ Keyframe ชุดทดสอบอยู่ใน Grid cell/บริเวณที่ผู้ตรวจระบุว่าถูกต้อง | Must | FR-LOC-04 |
| AC-LOC-04 | Boundary Check | Capture Path ไม่ทะลุขอบอาคารหรือกำแพงหลักโดยไม่มีการเตือน | Must | FR-LOC-06 |
| AC-LOC-05 | Confidence | Keyframe ทุกจุดมีค่า Confidence และจุดต่ำกว่าเกณฑ์ถูกทำเครื่องหมาย | Must | FR-LOC-04,06 |
| AC-LOC-06 | Open Evidence | คลิก Keyframe บนแบบแล้วเปิดภาพ 360 ณ เวลาที่สัมพันธ์กันได้ | Must | FR-VIEW-01,02 |
| AC-LOC-07 | Evidence Metadata | Viewer แสดง Capture Date, Timestamp, Floor และผล AI | Must | FR-VIEW-03 |
| AC-LOC-08 | Multi-floor Transition | ชุดทดสอบที่เดินข้ามชั้นสามารถระบุการเปลี่ยนชั้นได้ภายในคลาดเคลื่อน 15 วินาที | Should | FR-LOC-07 |

### วิธีสร้าง Ground Truth ตำแหน่ง

ผู้ประเมินเลือก Checkpoint อย่างน้อย 20 จุดต่อวิดีโอและระบุ Grid cell/บริเวณจริงจากภาพ จากนั้นเปรียบเทียบตำแหน่งที่ระบบคาดการณ์กับตำแหน่งอ้างอิง ไม่ใช้ระยะเซนติเมตรเป็นเกณฑ์ในรุ่นต้นแบบ

## 5. Human-verified Structural Progress (ใช้ตรวจรับใน Scope v2)

| ID | เกณฑ์ทดสอบ | ผลที่ต้องได้ | Priority |
|---|---|---|---|
| AC-MAN-01 | ตรวจองค์ประกอบ | ผู้ตรวจบันทึกสถานะ/ขั้นงานของคาน เสา พื้น และงานโครงสร้างหลังคาตามแปลนได้ | Must |
| AC-MAN-02 | Evidence | รายการที่ตรวจสามารถผูก Capture, Keyframe, ชั้น และวันที่เป็นหลักฐานได้ | Must |
| AC-MAN-03 | Calculation | คานใช้ความยาวและพื้นใช้พื้นที่ในการคำนวณ Progress ตามค่าที่ผู้ใช้ยืนยัน | Must |
| AC-MAN-04 | Incomplete Data | รายการที่ยังไม่ตรวจไม่ถูกตีความเป็น 0% และแสดงจำนวนตรวจแล้ว/ทั้งหมด | Must |
| AC-MAN-05 | Audit | การบันทึกใหม่เก็บผู้กรอก เวลา และประวัติเดิมไว้ครบ | Must |
| AC-MAN-06 | No Progress AI | หน้า Progress, Dashboard, CSV และ API สำหรับเว็บไม่แสดงหรือเรียก AI Progress | Must |

## 5A. AI Progress Tracking (ยกเลิกแล้ว — เก็บเป็นประวัติ Baseline 1.0)

| ID | เกณฑ์ทดสอบ | ผลที่ต้องได้ | Priority | SRS |
|---|---|---|---|---|
| AC-AI-01 | Beam Segment Prediction | ทุกช่วงที่วิเคราะห์ได้มีสถานะและ Confidence | Must | FR-AI-01,02,03 |
| AC-AI-02 | Visibility Handling | ช่วงที่ภาพไม่ครอบคลุมหรือถูกบังถูกระบุ Not Visible/Needs Review | Must | FR-AI-02,05 |
| AC-AI-03 | Coverage | ระบบรายงานสัดส่วนความยาวคานที่มีหลักฐานเพียงพอ | Must | FR-AI-05,06 |
| AC-AI-04 | Actual Formula | AI Actual เท่ากับผลรวมความยาวติดตั้งถ่วงน้ำหนักหารความยาวรวมที่นิยามไว้ | Must | FR-AI-04, BR-07 |
| AC-AI-05 | Classification Quality | F1-score สำหรับ Installed vs Not Installed อย่างน้อย 0.75 บน Test Set | Target | FR-AI-01,02 |
| AC-AI-06 | Progress Error | Mean Absolute Error ของ AI Actual เทียบ Human Verified ไม่เกิน 15 percentage points | Must | เป้าหมายวิจัย |
| AC-AI-07 | Per-date Result | ระบบคำนวณ AI Actual แยกวันที่ 681223, 681225, 681226 และ 681228 ได้ | Must | FR-DASH-01,02 |
| AC-AI-08 | Reproducibility | ผลทุกชุดมี Model Version, Capture และ Schedule Version | Must | FR-AI-03, BR-08 |

### กฎการแบ่ง Dataset

1. ห้ามสุ่มเฟรมติดกันจากช่วงเดียวกันไปอยู่ทั้ง Train และ Test
2. แบ่งข้อมูลตาม Capture Date หรือ Beam Segment group เพื่อลด Data Leakage
3. เก็บ Test Set ไว้จนกว่าการปรับโมเดลหลักจะเสร็จ
4. รายงานจำนวนภาพ จำนวน Beam Segment และสัดส่วนแต่ละสถานะ

## 6. Human Review and Research Comparison (เกณฑ์เปรียบเทียบ AI ยกเลิกแล้ว)

| ID | เกณฑ์ทดสอบ | ผลที่ต้องได้ | Priority | SRS |
|---|---|---|---|---|
| AC-REV-00 | Manual Actual Entry | Admin/Reviewer กรอก 0–100%, วันที่ และหมายเหตุราย Activity บนเว็บแล้วเปิดซ้ำพบข้อมูลครบ | Must | FR-REV-06 |
| AC-REV-00A | Immutable History | กรอก Activity เดิมสองครั้งแล้วพบทั้งสอง Record พร้อมผู้กรอก/เวลา และไม่มีคำสั่งแก้หรือลบย้อนหลัง | Must | FR-REV-07 |
| AC-REV-01 | Review Result | ผู้ตรวจยืนยัน แก้ หรือระบุประเมินไม่ได้ได้ | Must | FR-REV-01,02 |
| AC-REV-02 | Preserve AI Output | หลังแก้ ผล AI เดิมยังเปิดดูได้และไม่ถูกเขียนทับ | Must | FR-REV-03, BR-05 |
| AC-REV-03 | Audit | ระบบเก็บผู้ตรวจ เวลา และเหตุผลการแก้ | Must | FR-REV-02,04 |
| AC-REV-04 | Review Queue | ผล Confidence ต่ำแสดงก่อนผลอื่น | Must | FR-REV-05 |
| AC-REV-05 | Time Comparison | ระบบมีเวลาประเมิน AI pipeline และเวลาที่มนุษย์ใช้ตรวจชุดเดียวกัน | Must | เป้าหมายวิจัย |
| AC-REV-06 | Time Saving | เวลาที่มนุษย์ใช้หลังมี AI ช่วยลดลงอย่างน้อย 30% จากการประเมิน Manual-only | Target | เป้าหมายวิจัย |

## 7. Planned vs Human-verified Actual Dashboard

| ID | เกณฑ์ทดสอบ | ผลที่ต้องได้ | Priority | SRS |
|---|---|---|---|---|
| AC-DASH-01 | Planned Calculation | Planned คำนวณจาก Baseline Start/Finish ณ Capture Date ที่เลือก | Must | FR-SCH-07, BR-01,03 |
| AC-DASH-02 | Two Progress Values | แสดง Planned และผลตรวจจริงโดยผู้ใช้แยกป้ายชัดเจน | Must | Scope v2 |
| AC-DASH-03 | Variance | Variance คำนวณ Actual - Planned และใช้เครื่องหมายถูกต้อง | Must | FR-DASH-01 |
| AC-DASH-04 | Trend | กราฟเรียง Capture ตามวันที่และไม่ใช้ค่าปัจจุบันแทนค่าประวัติ | Must | FR-DASH-02, BR-02 |
| AC-DASH-05 | Heatmap | สีของ Beam Segment สอดคล้องกับสถานะ/เปอร์เซ็นต์ที่บันทึก | Must | FR-DASH-03 |
| AC-DASH-06 | Filters | กรองวันที่ กิจกรรม และสถานะ Review แล้วข้อมูลทุกส่วนเปลี่ยนสอดคล้องกัน | Must | FR-DASH-04 |
| AC-DASH-07 | CSV Export | ไฟล์ CSV มีวันที่ตรวจ กิจกรรม Planned ผลตรวจจริง สถานะ หมายเหตุ และข้อมูลอ้างอิงที่เกี่ยวข้อง | Must | Scope v2 |
| AC-DASH-08 | Evidence Trace | จากผล Dashboard เปิดไปยัง Capture/Keyframe หลักฐานได้ | Must | FR-DASH-07 |

## 8. Non-functional Acceptance Criteria

| ID | เกณฑ์ทดสอบ | ผลที่ต้องได้ | Priority |
|---|---|---|---|
| AC-NFR-01 | Page Response | หน้าทั่วไปเปิดภายใน 3 วินาทีในเครื่องและเครือข่ายทดสอบ | Target |
| AC-NFR-02 | Password Storage | ไม่พบรหัสผ่าน Plain Text ในฐานข้อมูลหรือ Log | Must |
| AC-NFR-03 | Project Isolation | ผู้ใช้ที่ไม่มีสิทธิ์เปิด URL ของโครงการอื่นแล้วไม่ได้ข้อมูล | Must |
| AC-NFR-04 | Retry | Processing Job ที่จำลองให้ล้มเหลวสามารถ Retry ได้ | Must |
| AC-NFR-05 | Traceability | สุ่มผลอย่างน้อย 10 รายการและย้อนถึง Capture, Keyframe, Model และ Schedule ได้ครบ | Must |
| AC-NFR-06 | Thai UI | หน้าหลักและข้อความ Error สำคัญอ่านเข้าใจได้เป็นภาษาไทย | Must |

## 9. Minimum Thesis Success Gate

ระบบถือว่าบรรลุเป้าหมายขั้นต่ำสำหรับโครงงานเมื่อ:

1. Import Baseline Schedule จาก Excel ได้
2. อัปโหลดและประมวลผล MP4 360 อย่างน้อย 4 Capture ได้
3. ผู้ใช้เลือกจุดเริ่มต้นหนึ่งจุดและระบบสร้าง Capture Path ได้
4. เปิดภาพ 360 จากตำแหน่งบนแบบได้
5. ผู้ใช้ตรวจ Progress งานโครงสร้างแยกองค์ประกอบ/ขั้นงานและผูกภาพหลักฐานได้
6. คำนวณ Actual จากค่าที่ผู้ใช้ยืนยัน โดยใช้ความยาว/พื้นที่ที่กำหนดได้
7. Dashboard แสดง Planned vs Actual หลายวันที่ถ่ายได้
8. รายการที่ยังไม่ตรวจไม่ถูกนับเป็น 0% และผลทุกค่าตรวจสอบย้อนกลับได้
9. เก็บผู้ตรวจ เวลา และประวัติการบันทึกโดยไม่เขียนทับข้อมูลเดิม
10. Export ผลทดลองเป็น CSV และย้อนกลับไปดูหลักฐานได้

ผล AI Progress เดิมไม่ใช่เกณฑ์ส่งงานและไม่ถูกนำมาแสดงเป็น Actual ในระบบ Scope v2

## 10. Stretch Goals ที่ไม่ทำให้ Core Gate ล้มเหลว

- Chunked upload สูงสุด 10 GB
- Multi-floor localization
- Side-by-side comparison
- PDF report
- Tracker งานก่อผนัง
- Tracker งานฉาบผนัง
- Revit/IFC import
- `.insv` server-side processing

## 11. รายการที่ผู้ใช้ต้องอนุมัติ

1. Localization วัดความถูกต้องระดับ Grid/บริเวณ ไม่ใช่ระดับเซนติเมตร
2. เกณฑ์ตำแหน่งถูกต้องขั้นต่ำ 80% ของ Keyframe ที่มี Ground Truth
3. F1-score เป้าหมายอย่างน้อย 0.75 สำหรับ Installed vs Not Installed
4. Progress MAE ต้องไม่เกิน 15 percentage points โดยยอมรับ Pass with Limitation ตามเงื่อนไขในข้อ 9
5. เป้าหมายลดเวลามนุษย์อย่างน้อย 30%
6. Multi-floor localization เป็น Stretch/Should ไม่ใช่ Core Gate
7. MP4 360 เป็น Input ที่ต้องผ่าน ส่วน `.insv` ไม่เป็น Core Gate
8. PDF report ไม่เป็น Core Gate แต่ CSV export เป็น Core Gate

## 12. บันทึกการอนุมัติ

| เวอร์ชัน | วันที่ | สถานะ | หมายเหตุ |
|---|---|---|---|
| 1.0 | 21 สิงหาคม 2026 | อนุมัติ | ผู้ใช้อนุมัติรอบที่ 1 และกำหนด AC-LOC-03 เป็น 80% |
