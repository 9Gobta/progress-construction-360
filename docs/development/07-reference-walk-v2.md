# Reference Walk Selection v2

วันที่ดำเนินการ: 23 สิงหาคม 2569

## ปัญหาที่พบ

ระบบรุ่นเดิมจัดอันดับ Capture อ้างอิงจาก Accuracy และ Mean error ของ Ground Truth
ในชุดพัฒนาเป็นหลัก แต่ค่าดังกล่าวเป็น Training Accuracy หลังมนุษย์แก้เส้นทางแล้ว จึงไม่ใช่
ตัวชี้วัดว่าภาพของวันใดคล้ายกับ Capture ใหม่ที่สุด ตัวอย่าง Capture `690110` ถูกจับคู่กับ
`681223` แม้จะมี Capture ชุดพัฒนาที่ใหม่กว่า

## การแก้ไข

รุ่น `stella-vslam-visual-graph-v2` ทำงานดังนี้

1. ดึง Capture ก่อนหน้าสูงสุด 5 วัน โดยรับเฉพาะ `DEVELOPMENT` ชั้นเดียวกัน
2. ใช้ ORB และ Homography RANSAC เปรียบเทียบภาพของ Capture ใหม่กับแต่ละ Reference
3. บังคับคู่ภาพแบบ one-to-one เพื่อลดปัญหาพื้นผิวซ้ำจับหลายตำแหน่ง
4. จัดอันดับจากจำนวน Visual Match และผลรวม Feature inliers
5. ใช้ Capture ล่าสุดเป็นตัวตัดสินเฉพาะเมื่อคะแนนภาพเท่ากัน
6. ใช้ RANSAC Affine และ Piecewise Drift Correction สร้างเส้นทางบนแปลน

ระบบไม่อ่าน Ground Truth หรือ Accuracy ของ Capture ที่กำลังทดสอบเพื่อเลือก Reference
และไม่อนุญาตให้ Capture `HOLDOUT_TEST` เป็น Reference Walk

## การตรวจสอบ

- API/localization tests ผ่านทั้งหมด 46 รายการ
- Ruff ผ่านโดยไม่มีข้อผิดพลาด
- Worker ถูกรีสตาร์ตและตอบ `pong` แล้ว

## กติกาการทดสอบถัดไป

ห้ามกดคำนวณใหม่หรือแก้แนว Capture `690110` เพื่อเลือกค่าของรุ่น v2 เพราะทราบผล Ground
Truth 65% แล้ว Capture นี้ใช้เป็น Error Analysis ได้เท่านั้น การวัดผล v2 ต้องใช้ Capture
วันใหม่ที่ไม่เคยใช้พัฒนาและต้องกำหนดเป็น `HOLDOUT_TEST` ก่อนประมวลผล จากนั้นจึงสร้าง
Ground Truth 20 จุดเพียงหนึ่งรอบ

## ผล Final Holdout

Capture `690111` ผ่าน 18 จาก 20 Ground Truth ที่ tolerance 3% คิดเป็น Localization
Accuracy 90.0% จึงผ่านเกณฑ์ขั้นต่ำ 80% ผลนี้เป็น Final Holdout ของ Vision Graph v2
และห้ามนำกลับมาใช้ปรับโมเดล
