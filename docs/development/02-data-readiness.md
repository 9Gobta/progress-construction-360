# Week 1 Data Readiness

> **Scope v2:** ข้อมูล AI Progress ในเอกสารนี้เป็นประวัติเดิม ค่า Actual ปัจจุบันมาจากผู้ตรวจบนเว็บเท่านั้น

วันที่ตรวจ: 21 สิงหาคม 2026

## 1. Schedule source

ไฟล์ต้นทาง: `Data/งานคานชั้น 1.xlsx`

| รายการ | ผลตรวจ |
|---|---|
| Sheet | `Task_Table1` |
| จำนวนแถวข้อมูล | 26 |
| จำนวนคอลัมน์ | 7 |
| WBS | `1` ถึง `1.2.1.3.5` |
| Baseline | `Baseline_Start` และ `Baseline_Finish` เป็น `NA` ทุกแถว |
| แผนที่ใช้ | `Start_Date` และ `Finish_Date` ตามที่เจ้าของโครงการอนุมัติ |
| Percent Complete ในไฟล์ปัจจุบัน | `0` ทุกแถว |

### Import mapping

| Excel | Database | กติกา |
|---|---|---|
| `Name` | `activities.name` | ตัดช่องว่างหัวท้าย; ห้ามว่าง |
| `WBS` | `activities.wbs` | เก็บเป็นข้อความ; ต้องไม่ซ้ำใน Schedule Version |
| `Start_Date` | `activities.planned_start` | ใช้เมื่อ Baseline เป็น `NA` |
| `Finish_Date` | `activities.planned_finish` | ใช้เมื่อ Baseline เป็น `NA` |
| `Baseline_Start` | `activities.planned_start` | ใช้เมื่อมีค่าครบคู่ Start/Finish |
| `Baseline_Finish` | `activities.planned_finish` | ใช้เมื่อมีค่าครบคู่ Start/Finish |
| `Percent_Complete` | ไม่นำเข้า | แสดงคำเตือนใน Preview; Actual ต้องกรอกบนเว็บ |

ค่า Percent Complete ในไฟล์เป็นข้อมูลจาก MS Project ณ วันที่ Export เท่านั้น ระบบต้นแบบไม่นำเข้าค่านี้ เพื่อป้องกันการปะปนระหว่างแผนกับผลหน้างาน Human Actual ต้องกรอกบนเว็บและเก็บประวัติแยกจาก AI Actual

ข้อสังเกต: ไม่ว่าค่าใน `Percent_Complete` จะเป็น `0`, `1` หรือ `100` ระบบจะแสดงว่าไม่นำเข้าและไม่ตีความอัตโนมัติ

## 2. Structural sheet

ไฟล์ต้นทาง: `Data/A-โครงสร้าง 11668.pdf`

| รายการ | ผลตรวจ |
|---|---|
| หน้าที่เลือก | หน้า 3 |
| Drawing No. | `ST-03` |
| ชื่อแบบ | แปลนโครงสร้างชั้น 1 |
| Scale ในแบบ | `1:100` |
| Grid ตัวเลข | `1–6` |
| Grid ตัวอักษร | `A–D` |
| ระยะรวมแนวนอน | 18.75 เมตร |
| ระยะอ้างอิงแนวตั้ง | 9.90 เมตร ไม่รวมส่วนยื่น 1.80 เมตร |
| Beam type ที่มองเห็น | `B1`, `B2`, `B3`, `B4`, `B6`, `CB4`, `CB6` |

Preview สำหรับ Web: `apps/web/public/plans/floor-1-structural.png`

ยังไม่สร้าง Beam Segment อัตโนมัติจากเส้นใน PDF เพราะต้องให้ผู้ใช้ตรวจขอบเขตและ code บน Web ก่อน เพื่อป้องกันเส้น Dimension, Grid และเส้นพื้นถูกตีความเป็นคาน

## 3. Locked decisions

- ห้องให้ผู้ใช้กรอกเองในภายหลัง
- ผู้ใช้อัปโหลด Capture แล้วเลือกชั้นและจุดเริ่มต้นเท่านั้น
- จุดเริ่มต้นเก็บเป็นพิกัด normalized `0–1` เพื่อรองรับภาพแบบหลายความละเอียด
- วิดีโอต้นฉบับเก็บใน Object Storage; Database เก็บ Metadata และ Object Key
- งาน AI ทำผ่าน Queue และแยกออกจาก Web Request
