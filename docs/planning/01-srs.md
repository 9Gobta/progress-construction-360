# Software Requirement Specification (SRS)

> **Scope Amendment v2.0 — 27 สิงหาคม 2026 (ใช้แทนข้อกำหนดเดิมเมื่อขัดกัน)**
>
> - ขอบเขต Progress เหลือเฉพาะ **งานโครงสร้างทั้งหมด** ไม่รวมงานสถาปัตยกรรม
> - ยกเลิก AI สำหรับประเมิน Progress; ค่า Actual 0–100% ให้ผู้ตรวจกรอกด้วยคนจากหลักฐานภาพ 360°
> - เส้นทางกล้องใช้ผลที่ระบบสร้างเป็นจุดตั้งต้น และอนุญาตให้คนปรับตำแหน่ง/สเกล/การหมุนเมื่อไม่ตรงแปลน
> - รองรับหลายบัญชีในโครงการ: `admin`, `reviewer`, `viewer` พร้อมบันทึกผู้กรอกและเวลา
> - เพิ่ม BIM Compare: ภาพ 360° เทียบโมเดลโครงสร้างจาก Revit แบบเคียงข้างกัน โดยต้นแบบรับไฟล์ IFC ที่ Export จาก Revit
> - ข้อกำหนด AI Progress, AI Accuracy, AI-vs-Human และงานสถาปัตยกรรมทั้งหมดในเอกสารฉบับเดิมถูกยกเลิก

## ระบบประเมินความก้าวหน้างานก่อสร้างจากวิดีโอ 360 องศา

| รายการ | ค่า |
|---|---|
| สถานะเอกสาร | Approved - Round 1 |
| เวอร์ชัน | 1.0 |
| วันที่ | 21 สิงหาคม 2026 |
| เป้าหมายส่งโครงงาน | 2 ตุลาคม 2026 |
| โครงการทดลอง | อาคารหอพัก ค.ส.ล. 4 ชั้น |
| กล้อง | Insta360 X5, 8K |
| AI Tracker รุ่นแรก | งานผูกเหล็กคานคอดิน |

## 1. วัตถุประสงค์

พัฒนาเว็บแอปพลิเคชันต้นแบบที่นำแบบแปลน แผนงาน และวิดีโอ 360 องศามาเชื่อมโยงกัน เพื่อให้ AI ประเมินความก้าวหน้าทางกายภาพที่มองเห็นได้ เปรียบเทียบ Planned Progress กับ Actual Progress และให้มนุษย์ตรวจยืนยันผล AI ได้

ระบบยึดหลักการของ OpenSpace Progress Tracking คือแยกแผนงาน (Schedule) ออกจากความก้าวหน้าที่สังเกตได้ (Observed/Actual) และเชื่อมผลกับหลักฐานภาพ โดยรายละเอียดการกรอกสถานะบนตารางอ้างอิงแนวทางของ Legacy OpenSpace Track ระบบไม่พัฒนาเครื่องมือวางแผนงานเต็มรูปแบบภายในเว็บ

## 2. เป้าหมายงานวิจัย

1. เปรียบเทียบเปอร์เซ็นต์ความก้าวหน้าที่ AI ประเมินกับมนุษย์จากข้อมูลภาพชุดเดียวกัน
2. เปรียบเทียบเวลาที่ AI และมนุษย์ใช้ในการประเมิน
3. วิเคราะห์ความคลาดเคลื่อนของ AI แยกตามวันที่ ตำแหน่ง และคุณภาพภาพ
4. แสดง Planned vs Actual พร้อมหลักฐานที่ตรวจสอบย้อนกลับได้

## 3. ขอบเขตที่ยืนยันแล้ว

1. ใช้ `Start_Date` และ `Finish_Date` จาก Excel รอบล่าสุดเป็น Baseline Version 1
2. ระบบไม่มีฟังก์ชันสร้าง Schedule เต็มรูปแบบ
3. ระบบ Import Schedule จาก Excel/CSV ที่ Export จาก MS Project
4. ระบบรับ MP4 360 แบบ equirectangular 2:1 ที่ Stitch แล้วเป็น Input หลักของ Visual SLAM; INSV ไม่ใช่เงื่อนไขของการคำนวณตำแหน่ง
5. ผู้ใช้เลือกชั้นและคลิกจุดเริ่มต้นบนแบบเพียงหนึ่งจุด ไม่ต้องวาดเส้นทางหรือระบุทิศเริ่มต้น
6. ระบบสร้าง Capture Path และผูก Keyframe กับตำแหน่งโดยอัตโนมัติ
7. หนึ่ง Capture ต้องอยู่บนชั้นเดียว หากเปลี่ยนชั้นต้องจบ Capture และเริ่มรายการใหม่ตาม Capture Protocol
8. AI Tracker รุ่นแรกตรวจงานผูกเหล็กคานคอดิน
9. Actual Progress รุ่นแรกคำนวณจากสัดส่วนความยาวช่วงคานที่ติดตั้งเหล็กแล้วต่อความยาวรวม
10. มนุษย์สามารถยืนยัน แก้ไข และระบุว่าไม่สามารถประเมินได้
11. ระบบเก็บผล AI เดิมและผลหลังมนุษย์ตรวจแยกจากกัน

## 4. ผู้ใช้งาน

### 4.1 Project Administrator

- สร้างและตั้งค่าโครงการ
- อัปโหลดแบบและ Schedule
- จับคู่กิจกรรมกับ AI Tracker
- จัดการ Capture และดูรายงานทั้งหมด

### 4.2 Reviewer

- เปิดดูวิดีโอและภาพ 360 องศา
- ตรวจและแก้ผล AI
- บันทึกเวลาที่ใช้ประเมิน
- ดู Planned vs Actual

### 4.3 Viewer

- ดู Dashboard, Capture Path, 360 Viewer และรายงาน
- ไม่มีสิทธิ์เปลี่ยนผล AI หรือข้อมูลโครงการ

สำหรับต้นแบบ ผู้ใช้หนึ่งบัญชีอาจมีทุกสิทธิ์ แต่ฐานข้อมูลต้องรองรับการแยกบทบาทในอนาคต

## 5. คำศัพท์สำคัญ

| คำ | ความหมาย |
|---|---|
| Capture | การบันทึกหน้างานหนึ่งครั้งด้วยวิดีโอ 360 องศา |
| Keyframe | ภาพที่ระบบดึงจากวิดีโอเพื่อระบุตำแหน่งและวิเคราะห์ AI |
| Capture Path | เส้นทางโดยประมาณของกล้องบนแบบแปลน |
| AI Tracker | ชุดกฎและโมเดล AI สำหรับงานก่อสร้างประเภทหนึ่ง |
| Planned Progress | ความก้าวหน้าที่ควรเป็นตาม Baseline Schedule ณ วันถ่าย |
| Human Actual | ความก้าวหน้า 0–100% ที่ผู้มีสิทธิ์กรอกบนเว็บตามวันที่สังเกต โดยเก็บเป็นประวัติและไม่เขียนทับ |
| AI Actual | ความก้าวหน้าที่ AI ประเมินก่อนมนุษย์แก้ไข |
| Verified Actual | ความก้าวหน้าหลังมนุษย์ตรวจยืนยัน |
| Beam Segment | ช่วงคานที่มีรหัสเฉพาะตาม Floor และ Grid ต้นทาง-ปลายทาง |
| Schedule Version | สำเนาแผนงานแต่ละครั้งที่ Import โดยไม่เขียนทับข้อมูลเก่า |

## 6. Functional Requirements

ระดับความสำคัญ:

- **Must**: ต้องมีในรุ่นส่งเล่ม
- **Should**: ควรมีหากส่วน Must เสร็จและผ่านการทดสอบ
- **Could**: งานต่อยอดหลังส่งหรือใช้เป็นแนวทางบริษัท

### 6.1 Authentication and Authorization

| ID | Requirement | Priority |
|---|---|---|
| FR-AUTH-01 | ผู้ใช้เข้าสู่ระบบและออกจากระบบได้ | Must |
| FR-AUTH-02 | ระบบจำกัดสิทธิ์ตาม Admin, Reviewer และ Viewer | Should |
| FR-AUTH-03 | ระบบบันทึกผู้สร้างหรือผู้แก้ข้อมูลสำคัญ | Must |

### 6.2 Project Setup

| ID | Requirement | Priority |
|---|---|---|
| FR-PRJ-01 | ผู้ใช้สร้าง แก้ไข และเปิดโครงการได้ | Must |
| FR-PRJ-02 | ผู้ใช้กำหนดชื่อโครงการ ที่ตั้ง เขตเวลา และคำอธิบายได้ | Must |
| FR-PRJ-03 | ผู้ใช้เพิ่มชั้นและกรอกรายชื่อห้องเองได้ | Should |
| FR-PRJ-04 | ระบบรองรับหลายโครงการโดยข้อมูลไม่ปะปนกัน | Must |

### 6.3 Sheets, Floors and Structural Grid

| ID | Requirement | Priority |
|---|---|---|
| FR-SHT-01 | ผู้ใช้อัปโหลดแบบ PDF หรือภาพแยกตามชั้นได้ | Must |
| FR-SHT-02 | ระบบแสดงแบบแปลนที่ซูม เลื่อน และคลิกตำแหน่งได้ | Must |
| FR-SHT-03 | ผู้ใช้กำหนด Scale และจุดอ้างอิงบนแบบได้ | Must |
| FR-SHT-04 | ระบบจัดเก็บ Grid และ Beam Segment ของชั้น 1 ได้ | Must |
| FR-SHT-05 | ผู้ใช้เพิ่ม แก้ หรือลบ Beam Segment บนแบบได้ | Should |
| FR-SHT-06 | ระบบนำข้อมูลห้องหรือองค์ประกอบจาก Revit/IFC ได้ | Could |

### 6.4 Schedule Import and Versioning

| ID | Requirement | Priority |
|---|---|---|
| FR-SCH-01 | ผู้ใช้ Import Schedule รูปแบบ `.xlsx` หรือ `.csv` ได้ | Must |
| FR-SCH-02 | ระบบอ่าน Name, WBS, Start Date และ Finish Date; หากมี Percent Complete ให้แสดงว่าไม่นำเข้ามาเป็น Actual | Must |
| FR-SCH-03 | ระบบแสดง Preview และข้อผิดพลาดก่อนยืนยัน Import | Must |
| FR-SCH-04 | ผู้ใช้จับคู่คอลัมน์ต้นทางกับฟิลด์ของระบบได้ | Must |
| FR-SCH-05 | การ Import แต่ละครั้งสร้าง Schedule Version ใหม่และไม่เขียนทับ Baseline | Must |
| FR-SCH-06 | ผู้ใช้เลือก Schedule Version ที่ใช้เปรียบเทียบได้ | Must |
| FR-SCH-07 | ระบบคำนวณ Planned Progress จาก Start/Finish และปฏิทินทำงานที่กำหนด | Must |
| FR-SCH-08 | ระบบอ่านไฟล์ `.mpp` โดยตรง | Could |

### 6.5 Activity-to-Tracker Mapping

| ID | Requirement | Priority |
|---|---|---|
| FR-MAP-01 | ผู้ใช้จับคู่กิจกรรม Schedule กับ AI Tracker ได้ | Must |
| FR-MAP-02 | ผู้ใช้จับคู่กิจกรรมกับ Floor, Grid หรือ Beam Segment ได้ | Must |
| FR-MAP-03 | ระบบแสดงกิจกรรมที่ยังไม่ได้จับคู่ | Must |
| FR-MAP-04 | ระบบไม่สร้าง AI Actual สำหรับกิจกรรมที่ไม่มี Tracker | Must |
| FR-MAP-05 | ผู้ใช้กำหนดน้ำหนักกิจกรรมหรือปริมาณรวมได้ | Should |

### 6.6 Capture Upload and Processing

| ID | Requirement | Priority |
|---|---|---|
| FR-CAP-01 | ผู้ใช้อัปโหลด MP4 360 องศาแบบ equirectangular 2:1 ที่ Stitch แล้วได้ | Must |
| FR-CAP-02 | ระบบรองรับการอัปโหลดไฟล์ขนาดอย่างน้อย 2 GB | Must |
| FR-CAP-03 | ระบบรองรับ Chunked/Resumable Upload สำหรับไฟล์สูงสุดเป้าหมาย 10 GB | Should |
| FR-CAP-04 | ผู้ใช้ระบุวันที่ถ่าย ผู้ถ่าย และหมายเหตุได้ | Must |
| FR-CAP-05 | ระบบตรวจชนิดไฟล์ ความละเอียด ระยะเวลา และความเสียหายเบื้องต้น | Must |
| FR-CAP-06 | ระบบประมวลผลวิดีโอเป็น Background Job แม้ผู้ใช้ปิดหน้าเว็บ | Must |
| FR-CAP-07 | ระบบแสดงสถานะ Queued, Stitching, Extracting, Localizing, Analyzing, Review และ Completed | Must |
| FR-CAP-08 | ระบบสร้าง Camera Pose จากภาพใน MP4 โดยไม่ต้องอาศัย GPS หรือพิกัดในไฟล์ | Must |
| FR-CAP-09 | หนึ่ง Capture รองรับหนึ่งชั้น ระบบแสดงคำเตือนให้จบ Capture ก่อนเปลี่ยนชั้น | Must |
| FR-CAP-10 | ระบบรับ LRV/GPX เป็นไฟล์ประกอบของ Capture | Could |

### 6.7 Start Point and Automatic Localization

| ID | Requirement | Priority |
|---|---|---|
| FR-LOC-01 | ผู้ใช้เลือกชั้นเริ่มต้นและคลิกจุดเริ่มต้นบนแบบได้ | Must |
| FR-LOC-02 | ระบบไม่บังคับให้ผู้ใช้ระบุทิศหรือวาดเส้นทาง | Must |
| FR-LOC-03 | ระบบดึง Keyframe และประมาณเส้นทางจากวิดีโออัตโนมัติ | Must |
| FR-LOC-04 | ระบบผูก Keyframe กับตำแหน่งบนแบบ แสดง Confidence และมีความถูกต้องระดับ Grid/บริเวณอย่างน้อย 80% ของ Keyframe ที่มี Ground Truth | Must |
| FR-LOC-05 | ระบบแสดง Capture Path และจุด Keyframe บนแบบ | Must |
| FR-LOC-06 | ระบบแจ้งช่วงเส้นทางที่ Confidence ต่ำ | Must |
| FR-LOC-07 | ระบบปฏิเสธหรือส่งตรวจ Capture ที่ตรวจพบการเปลี่ยนชั้น และให้แบ่งเป็น Capture ใหม่ | Should |
| FR-LOC-08 | ผู้ตรวจสามารถแก้ตำแหน่ง Keyframe ที่ผิดได้ | Should |

### 6.8 360 Viewer and Evidence

| ID | Requirement | Priority |
|---|---|---|
| FR-VIEW-01 | ผู้ใช้เปิดดูภาพนิ่ง 360 ที่ระบบดึงจากไฟล์ต้นทางได้โดยไม่ต้องเล่นวิดีโอต่อเนื่อง | Must |
| FR-VIEW-02 | การคลิก Keyframe บนแบบเปิดภาพ ณ ตำแหน่งนั้น | Must |
| FR-VIEW-03 | Viewer แสดงวันที่ เวลา ชั้น ตำแหน่ง และผล AI | Must |
| FR-VIEW-04 | ผู้ใช้เปรียบเทียบตำแหน่งเดียวกันสองวันแบบ Side-by-side ได้ | Should |
| FR-VIEW-05 | ระบบแสดงภาพหลักฐานที่ใช้ตัดสินแต่ละ Beam Segment | Must |

### 6.9 AI Progress Tracking

| ID | Requirement | Priority |
|---|---|---|
| FR-AI-01 | AI Tracker รุ่นแรกตรวจการติดตั้งเหล็กคานคอดิน | Must |
| FR-AI-02 | ระบบประเมินแต่ละ Beam Segment เป็น Not Visible, Not Started, Partial, Installed หรือ Needs Review | Must |
| FR-AI-03 | ระบบเก็บ Confidence และ Model Version ทุก Prediction | Must |
| FR-AI-04 | ระบบคำนวณ AI Actual จากความยาวที่ติดตั้งต่อความยาวรวม | Must |
| FR-AI-05 | ระบบไม่รวมช่วง Not Visible ในผลโดยไม่มีคำเตือน Coverage | Must |
| FR-AI-06 | ระบบแสดง Coverage ของพื้นที่ที่วิเคราะห์ได้ | Must |
| FR-AI-07 | ระบบรองรับ Tracker งานก่อและงานฉาบในอนาคต | Could |

### 6.10 Human Review

| ID | Requirement | Priority |
|---|---|---|
| FR-REV-01 | ผู้ตรวจยืนยันหรือแก้สถานะและเปอร์เซ็นต์ของ Beam Segment ได้ | Must |
| FR-REV-02 | ผู้ตรวจระบุสาเหตุ เช่น ถูกบัง ภาพเบลอ ตำแหน่งผิด หรือ AI ตรวจผิดได้ | Must |
| FR-REV-03 | ระบบเก็บ AI Actual เดิมและ Verified Actual แยกกัน | Must |
| FR-REV-04 | ระบบบันทึกผู้ตรวจ เวลาเริ่ม เวลาสิ้นสุด และเวลาที่ใช้ | Must |
| FR-REV-05 | ระบบแสดงรายการผล Confidence ต่ำก่อน | Must |
| FR-REV-06 | ผู้มีสิทธิ์กรอก Human Actual 0–100% รายกิจกรรมและวันที่สังเกตบนเว็บ พร้อมหมายเหตุและ Capture อ้างอิงได้ | Must |
| FR-REV-07 | การกรอก Human Actual ทุกครั้งสร้าง Record ใหม่ พร้อมผู้กรอกและเวลา โดยไม่มี API แก้ไขหรือลบย้อนหลัง | Must |

### 6.11 Dashboard and Reporting

| ID | Requirement | Priority |
|---|---|---|
| FR-DASH-01 | Dashboard แสดง Planned, Human Actual, AI Actual, Verified Actual และ Variance ตามวันที่ | Must |
| FR-DASH-02 | ระบบแสดง Progress Trend ของหลาย Capture | Must |
| FR-DASH-03 | ระบบแสดง Heatmap ของ Beam Segment บนแบบ | Must |
| FR-DASH-04 | ผู้ใช้กรองตามวันที่ ชั้น กิจกรรม และสถานะ Review ได้ | Must |
| FR-DASH-05 | ระบบส่งออกผลเป็น CSV ได้ | Must |
| FR-DASH-06 | ระบบสร้างรายงาน PDF ได้ | Should |
| FR-DASH-07 | รายงานทุกค่ามีลิงก์หรือรหัสอ้างอิงกลับไปยังภาพหลักฐาน | Must |

## 7. Business Rules

| ID | กฎ |
|---|---|
| BR-01 | Baseline Version 1 ใช้ Start/Finish จากไฟล์ `งานคานชั้น 1.xlsx` ที่ผู้ใช้ยืนยัน |
| BR-02 | Percent Complete ปัจจุบันใน Schedule ไม่ใช้เป็น Actual ย้อนหลัง |
| BR-02A | Excel ใช้เป็นข้อมูลแผนเท่านั้น; Human Actual ต้องกรอกบนเว็บและเก็บแยกจาก AI Actual |
| BR-03 | Planned Progress คำนวณ ณ Capture Date ไม่ใช่วันที่เปิด Dashboard |
| BR-04 | งานที่ไม่มี AI Tracker ต้องแสดงเป็น Manual Only หรือ Unsupported |
| BR-05 | AI Prediction ห้ามถูกเขียนทับเมื่อมนุษย์แก้ ต้องสร้าง Review Record แยก |
| BR-06 | ถ้า Coverage ต่ำกว่าเกณฑ์ ระบบต้องเตือนและไม่แสดงผลเป็นค่าที่เชื่อถือได้โดยไม่มีคำเตือน |
| BR-07 | Actual Progress ของงานผูกเหล็กคานคอดินถ่วงน้ำหนักด้วยความยาว Beam Segment |
| BR-08 | Schedule Version และ Model Version ต้องติดกับผลทุกครั้งเพื่อทำซ้ำการทดลองได้ |

## 8. Non-Functional Requirements

### 8.1 Performance

| ID | Requirement |
|---|---|
| NFR-PERF-01 | หน้าเว็บทั่วไปตอบสนองภายใน 3 วินาทีในเครือข่ายภายในสำหรับข้อมูลต้นแบบ |
| NFR-PERF-02 | การอัปโหลดต้องแสดงเปอร์เซ็นต์ ความเร็ว และข้อผิดพลาด |
| NFR-PERF-03 | วิดีโอ 8K ระยะประมาณ 90 วินาทีต้องประมวลผลครบภายในเป้าหมาย 30 นาทีบนเครื่อง RTX 4050 |
| NFR-PERF-04 | งานประมวลผลหลายขั้นต้องไม่ทำให้ Web Request ค้าง |

### 8.2 Reliability and Traceability

| ID | Requirement |
|---|---|
| NFR-REL-01 | งานที่ล้มเหลวต้อง Retry ได้โดยไม่อัปโหลดไฟล์ใหม่ถ้าไฟล์ยังสมบูรณ์ |
| NFR-REL-02 | ระบบเก็บ Log ของ Upload, Import, Processing, Prediction และ Review |
| NFR-REL-03 | ผลทุกค่าต้องย้อนกลับไปหา Capture, Keyframe, Model Version และ Schedule Version ได้ |

### 8.3 Security

| ID | Requirement |
|---|---|
| NFR-SEC-01 | รหัสผ่านต้องไม่เก็บเป็น Plain Text |
| NFR-SEC-02 | ตรวจชนิดและขนาดไฟล์ก่อนประมวลผล |
| NFR-SEC-03 | ผู้ใช้เข้าถึงเฉพาะโครงการที่มีสิทธิ์ |
| NFR-SEC-04 | ไฟล์วิดีโอไม่เปิดเป็น Public URL โดยค่าเริ่มต้น |

### 8.4 Usability

| ID | Requirement |
|---|---|
| NFR-USE-01 | UI รุ่นแรกใช้ภาษาไทย โดยใช้คำเทคนิคอังกฤษในวงเล็บเมื่อจำเป็น |
| NFR-USE-02 | ผู้ใช้ต้องเห็นขั้นตอนถัดไปและสถานะงานประมวลผลอย่างชัดเจน |
| NFR-USE-03 | ค่า Planned, AI Actual และ Verified Actual ต้องใช้สีและป้ายกำกับที่ไม่สับสน |
| NFR-USE-04 | หน้าหลักรองรับจอคอมพิวเตอร์ความกว้าง 1366 พิกเซลขึ้นไป |

### 8.5 Maintainability and Extensibility

| ID | Requirement |
|---|---|
| NFR-MNT-01 | แยก Video Processing, Localization และ Progress AI เป็น Worker/Module |
| NFR-MNT-02 | เพิ่ม AI Tracker ใหม่ได้โดยไม่เปลี่ยนโครงสร้าง Capture หลัก |
| NFR-MNT-03 | Database migration และ Model Version ต้องถูกบันทึก |
| NFR-MNT-04 | รองรับการย้าย File Storage จาก Local/MinIO ไป S3-compatible ในอนาคต |

## 9. ข้อมูลทดลองเริ่มต้น

| Capture | วันที่ | รูปแบบ | Resolution | หมายเหตุ |
|---|---|---|---|---|
| 681223 | 23 ธ.ค. 2025 | MP4 360 | 7680x3840 | ก่อนกิจกรรมตามแผน/เริ่มเห็นเหล็กบางส่วน |
| 681225 | 25 ธ.ค. 2025 | MP4 360 | 7680x3840 | Capture สั้นประมาณ 9 วินาที |
| 681226 | 26 ธ.ค. 2025 | MP4 360 | 7680x3840 | เห็นแนวเหล็กหลายตำแหน่ง |
| 681228 | 28 ธ.ค. 2025 | MP4 360 | 7680x3840 | ชุดทดสอบหลักที่ผู้ใช้ยืนยัน |

## 10. ข้อจำกัดและความเสี่ยง

1. ข้อมูลมาจากโครงการเดียว จึงยังสรุปความสามารถทั่วไปกับโครงการอื่นไม่ได้
2. เส้นทางเดินไม่ซ้ำ ผู้ถ่ายสามคน และบาง Capture เดินข้ามชั้น
3. Visual SLAM จากภาพ 360 องศาอาจมี Drift และ Scale Ambiguity
4. วิดีโอช่วงแรกมีจำนวนวันจำกัดและส่วนใหญ่เป็นสถานะงานใกล้เคียงกัน
5. Ground Truth มาจากนักศึกษาเป็นหลัก อาจมีอคติของผู้ประเมิน
6. แบบและวิดีโอต้องจัดแนวกันก่อนจึงจะผูกกับ Beam Segment ได้
7. การรองรับ `.insv` เป็น Must แต่การ Stitch จริงขึ้นกับการได้รับและติดตั้ง Insta360 MediaSDK ที่แจกจ่ายแยก; ระบบต้องเก็บไฟล์และ Retry ได้หาก Worker ยังไม่พร้อม
8. เวลาพัฒนารวมการเขียนเล่มเหลือประมาณหกสัปดาห์

## 11. Out of Scope สำหรับรุ่นส่งเล่ม

- Schedule authoring เต็มรูปแบบ
- Critical Path, Resource Leveling และ Cost Control
- อ่าน `.mpp` โดยตรง
- BIM Compare และ AR Overlay
- Mobile Capture Application
- Billing และ Subscription
- Multi-company SaaS เต็มรูปแบบ
- ตรวจงานก่อสร้างทุกประเภท
- รับรองความแม่นยำระดับงานตรวจรับหรือการเบิกจ่ายจริง

## 12. ประเด็นสำหรับอนุมัติรอบที่ 1

โปรดพิจารณาและอนุมัติหรือขอแก้ไขประเด็นต่อไปนี้:

1. AI Tracker รุ่นส่งเล่มโฟกัสงานผูกเหล็กคานคอดิน
2. ระบบใช้ Import Schedule เท่านั้น ไม่สร้างแผนงานเต็มรูปแบบ
3. ผู้ใช้เลือกชั้นและจุดเริ่มต้นหนึ่งจุด ไม่ระบุทิศและไม่วาดเส้นทาง
4. เดิมอนุมัติ MP4 360 เป็น Input หลัก; แก้ไขภายหลังให้ INSV เป็น Input หลักร่วมและใช้ MP4 เป็น Fallback
5. Multi-floor localization เป็น Should ไม่ใช่เงื่อนไขบังคับผ่านโครงงาน
6. PDF Report เป็น Should แต่ CSV Export เป็น Must
7. UI รุ่นแรกเป็นภาษาไทยและเน้นใช้งานบนคอมพิวเตอร์
8. เกณฑ์ AI และ Localization ใช้ตามเอกสาร Acceptance Criteria

## 13. บันทึกการอนุมัติ

| เวอร์ชัน | วันที่ | สถานะ | หมายเหตุ |
|---|---|---|---|
| 1.0 | 21 สิงหาคม 2026 | อนุมัติ | ผู้ใช้อนุมัติรอบที่ 1 และกำหนดความถูกต้อง Localization ขั้นต่ำ 80% |
