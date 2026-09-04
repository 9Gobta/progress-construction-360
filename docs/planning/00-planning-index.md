# Planning Package Index

## ระบบประเมินความก้าวหน้างานก่อสร้างจากวิดีโอ 360 องศา

| รายการ | ค่า |
|---|---|
| สถานะชุดเอกสาร | Approved |
| เวอร์ชันชุดเอกสาร | 2.0 |
| วันที่ปิด Planning Baseline | 21 สิงหาคม 2026 |
| วันที่อนุมัติ Scope v2 | 27 สิงหาคม 2026 |
| วันส่งเล่ม | 2 ตุลาคม 2026 |
| ขอบเขตปัจจุบัน | งานโครงสร้าง ตรวจ Progress โดยผู้ใช้จากหลักฐานภาพ 360 |

> Scope v2 ใน [Human Structural Progress + BIM Compare](09-scope-v2-human-structural-bim.md)
> ใช้แทนข้อกำหนด AI Progress ใน Baseline 1.0 ทุกกรณี โดยยังคง AI/CV สำหรับ Localization
> และเก็บผล Prediction เดิมไว้เป็นประวัติแบบอ่านอย่างเดียว

## 1. เอกสารที่อนุมัติแล้ว

| ลำดับ | เอกสาร | เวอร์ชัน | รอบอนุมัติ | ใช้ตอบคำถาม |
|---:|---|---:|---:|---|
| 1 | [Software Requirement Specification](01-srs.md) | 1.0 | 1 | ระบบต้องทำอะไรและไม่ทำอะไร |
| 2 | [Acceptance Criteria](02-acceptance-criteria.md) | 1.0 | 1 | จะพิสูจน์ว่าต้นแบบสำเร็จอย่างไร |
| 3 | [User Flow](03-user-flow.md) | 1.0 | 2 | ผู้ใช้ทำงานแต่ละขั้นอย่างไร |
| 4 | [Wireframes](04-wireframes.md) | 1.0 | 2 | หน้าหลักมีองค์ประกอบและสถานะใดบ้าง |
| 5 | [System Architecture](05-system-architecture.md) | 1.0 | 3 | ส่วนประกอบระบบเชื่อมต่อกันอย่างไร |
| 6 | [ER Diagram and Data Model](06-er-diagram.md) | 1.0 | 3 | ข้อมูลและความสัมพันธ์ถูกเก็บอย่างไร |
| 7 | [AI and Data Pipeline](07-ai-data-pipeline.md) | 1.0 | 4 | วิดีโอถูกแปลงเป็นผล AI และ Progress อย่างไร |
| 8 | [Development Roadmap](08-development-roadmap.md) | 1.0 | 4 | ต้องพัฒนาและทดสอบอะไรเมื่อใด |
| 9 | [Scope v2 — Human Structural Progress + BIM Compare](09-scope-v2-human-structural-bim.md) | 2.0 | เจ้าของโครงการ | ขอบเขตที่ใช้พัฒนาและตรวจรับในปัจจุบัน |

## 2. Planning Baseline ที่ล็อกแล้ว

1. โครงการทดลองเป็นอาคารหอพัก ค.ส.ล. 4 ชั้น
2. Progress งานโครงสร้างให้ผู้ตรวจกรอกและยืนยันจากหลักฐานภาพ 360 เท่านั้น
3. Input หลักเป็น MP4 360 equirectangular 2:1 สูงสุด 8K
4. ผู้ใช้เลือก Starting Floor และ Start Point หนึ่งจุด ไม่ต้องระบุทิศหรือวาดเส้นทาง
5. Baseline Schedule ใช้ `Start_Date` และ `Finish_Date` จาก Excel รอบล่าสุด
6. Actual Progress คำนวณจากค่าที่ผู้ใช้ยืนยัน โดยใช้ความยาวหรือพื้นที่ตามชนิดองค์ประกอบ
7. ระบบเก็บผู้กรอก เวลา และหลักฐานโดยไม่เขียนทับประวัติเดิม
8. รายการที่ยังไม่ได้ตรวจต้องไม่ถูกนับเป็น 0% และต้องแสดงจำนวนที่ตรวจแล้ว
9. Localization Raw Accuracy ระดับ Grid/บริเวณต้องไม่น้อยกว่า 80%
10. ไม่มีเกณฑ์ F1/MAE สำหรับ Progress; เกณฑ์ AI/CV คงไว้เฉพาะ Localization
11. CSV Export เป็น Must; PDF, Revit/IFC และ `.insv` processing เป็นงานภายหลัง
12. Feature freeze วันที่ 25 กันยายน 2026 และส่งเล่มวันที่ 2 ตุลาคม 2026

## 3. Technology Baseline

| Layer | Technology |
|---|---|
| Frontend | Next.js + TypeScript |
| Backend | FastAPI + Python |
| Database | PostgreSQL |
| Background jobs | Celery + Redis |
| Object storage | MinIO/S3-compatible storage |
| Video | FFmpeg/ffprobe |
| AI/CV | PyTorch, TorchVision, OpenCV |
| Local deployment | Docker Compose สำหรับ Infrastructure; Native/WSL2 GPU Worker |

## 4. Change-control Rule

เอกสารทั้ง 8 ฉบับเป็น Planning Baseline 1.0 ตั้งแต่วันที่ 21 สิงหาคม 2026 การเปลี่ยน Must Requirement, เกณฑ์วิจัย, Schema หลัก หรือวัน Gate ต้อง:

1. บันทึกเหตุผลและผลกระทบต่อเวลา/ผลวิจัย
2. เพิ่มเวอร์ชันเอกสารที่เกี่ยวข้อง ไม่แก้ประวัติอนุมัติเดิม
3. ปรับ Acceptance Criteria และ Roadmap ให้สอดคล้อง
4. ได้รับการยืนยันจากเจ้าของโครงการก่อนนำไปพัฒนา

การแก้คำผิด รายละเอียด Implementation หรือ Bug ที่ไม่เปลี่ยนความหมายของ Baseline ไม่ต้องเปิดรอบอนุมัติใหม่ แต่ต้องบันทึกใน Change Log ของโครงการ

## 5. ลำดับการใช้งานเอกสารระหว่างพัฒนา

1. เลือกงานจาก Roadmap
2. ตรวจ Must/Should/Could ใน SRS
3. ทำตาม User Flow และ Wireframe
4. ใช้ Architecture และ ER Diagram เป็นขอบเขตการออกแบบโค้ด/ข้อมูล
5. ใช้ AI/Data Pipeline เมื่อทำ Worker, Dataset และ Model
6. ปิดงานเมื่อ Acceptance Criteria มีหลักฐาน Pass

## 6. Definition of Planning Complete

- เอกสารที่ผู้ใช้ขอทั้ง 8 รายการมีครบ
- ทุกฉบับมีเวอร์ชันและประวัติการอนุมัติ
- เกณฑ์ Localization 80% สอดคล้องกันใน SRS, Acceptance Criteria และ AI Pipeline
- ขอบเขต MVP/Stretch/Future แยกชัดเจน
- Roadmap มี Gate ก่อนวันส่งและกำหนด Feature freeze
- สามารถเริ่ม Development Week 1 โดยไม่ต้องตัดสินใจ Architecture หลักใหม่
