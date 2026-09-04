# INSV ingestion และ GPU Stitching

อัปเดต: 21 สิงหาคม 2026

## สถานะที่พัฒนาแล้ว

- หน้า Capture รับ `.mp4` และ `.insv` สูงสุด 10 GB ผ่าน Multipart/Resumable Upload
- Object Storage เก็บไฟล์ต้นฉบับตามนามสกุลจริง
- MP4 แบบ equirectangular 2:1 เข้า Pipeline เดิมโดยตรง
- INSV เปลี่ยน Capture เป็น `STITCHING` และเรียก GPU Stitcher ก่อน Validate/Extract/Localize
- หากยังไม่มี Stitcher งานจบแบบตรวจสอบได้ด้วย `STITCHER_REQUIRED`; ไฟล์ต้นฉบับไม่ถูกลบและ Retry ได้หลังติดตั้ง SDK

## Dependency ที่ไม่เก็บใน Repository

Insta360 Desktop MediaSDK ต้องสมัครและติดตั้งแยก เนื่องจากเป็น SDK ภายนอกที่มีเงื่อนไขการแจกจ่าย ระบบอ่านตำแหน่ง executable จาก:

```env
INSTA360_STITCHER_PATH=D:\Insta360SDK\bin\progress-insta360-stitcher.exe
INSTA360_STITCH_TIMEOUT_SECONDS=7200
```

## CLI contract ของ MediaSDK wrapper

Backend เรียก executable ด้วยรูปแบบ:

```text
progress-insta360-stitcher.exe
  --input <absolute-source.insv>
  --output <absolute-stitched.mp4>
  --width 5760
  --height 2880
  --flowstate
  --direction-lock
```

ข้อกำหนดของ Wrapper:

1. Exit code `0` เมื่อสำเร็จ และไม่เป็น `0` เมื่อผิดพลาด
2. สร้าง MP4 equirectangular อัตราส่วน 2:1 ที่ path จาก `--output`
3. เขียนรายละเอียด Error ลง stderr
4. ใช้ Insta360 MediaSDK สำหรับ X5 พร้อม FlowState และ Direction Lock
5. ห้ามเขียนทับหรือลบ INSV ต้นฉบับ

## ลำดับสถานะ

```text
UPLOADING -> QUEUED -> STITCHING -> VALIDATING
          -> EXTRACTING_KEYFRAMES -> LOCALIZING
          -> READY / REVIEW_REQUIRED
```

หากเครื่อง Worker ยังไม่มี SDK:

```text
STITCHING -> STITCHER_REQUIRED
```

หลังติดตั้ง SDK ให้กด `Retry Processing` ที่หน้า Capture โดยไม่ต้องอัปโหลด INSV ใหม่
