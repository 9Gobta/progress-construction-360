"""Export presentation-ready evidence from the real 360 processing artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "presentation-assets"
KEYFRAMES = ROOT / ".tmp" / "capture-84e18039-all-keyframes"
FACES = ROOT / ".tmp" / "capture-84e18039-sfm" / "faces"
PATH_JSON = ROOT / "Data" / "derived" / "capture-84e18039-sfm-path.json"
FONT = Path("C:/Windows/Fonts/tahoma.ttf")
FONT_BOLD = Path("C:/Windows/Fonts/tahomabd.ttf")


def font(size: int, bold: bool = False):
    return ImageFont.truetype(str(FONT_BOLD if bold else FONT), size)


def canvas(title: str, subtitle: str):
    image = Image.new("RGB", (1920, 1080), "#f4f7f5")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1920, 128), fill="#073f30")
    draw.text((70, 34), title, font=font(38, True), fill="white")
    draw.text((72, 84), subtitle, font=font(20), fill="#bfe1d4")
    return image, draw


def fit(path: Path, size: tuple[int, int]):
    image = Image.open(path).convert("RGB")
    image.thumbnail(size, Image.Resampling.LANCZOS)
    background = Image.new("RGB", size, "#101813")
    background.paste(image, ((size[0] - image.width) // 2, (size[1] - image.height) // 2))
    return background


def export_keyframes():
    image, draw = canvas(
        "การดึง Keyframe จากวิดีโอ 360",
        "Capture จริง 23/12/2568 · MP4 Equirectangular 7680×3840 · Sampling ทุก 0.5 วินาที",
    )
    names = [("000000000.jpg", "00:00.0"), ("000030000.jpg", "00:30.0"), ("000060000.jpg", "01:00.0"), ("000090000.jpg", "01:30.0")]
    for index, (name, timestamp) in enumerate(names):
        x = 70 + (index % 2) * 920
        y = 175 + (index // 2) * 415
        image.paste(fit(KEYFRAMES / name, (850, 340)), (x, y))
        draw.rounded_rectangle((x + 18, y + 18, x + 155, y + 60), 9, fill="#073f30")
        draw.text((x + 34, y + 27), timestamp, font=font(18, True), fill="white")
    draw.text((70, 1018), "ผลจริง: 182 panorama frames จากวิดีโอ 91.1 วินาที พร้อม timestamp สำหรับอ้างอิงหลักฐาน", font=font(21, True), fill="#073f30")
    image.save(OUT / "01-keyframe-extraction.png")


def export_vslam():
    image, draw = canvas(
        "VSLAM / Structure-from-Motion",
        "แปลงภาพ 360 เป็นมุมมอง Perspective → จับ Feature → คำนวณ Camera Pose และเส้นทางสัมพัทธ์",
    )
    face_names = ["0000_0_0.jpg", "0000_1_0.jpg", "0000_2_0.jpg", "0000_3_0.jpg"]
    for index, name in enumerate(face_names):
        x = 60 + (index % 2) * 430
        y = 175 + (index // 2) * 330
        image.paste(fit(FACES / name, (390, 285)), (x, y))
    draw.text((60, 855), "Cubemap faces จาก panorama เวลา 00:00", font=font(21, True), fill="#073f30")
    data = json.loads(PATH_JSON.read_text(encoding="utf-8"))
    samples = data["samples"]
    plot = Image.new("RGB", (870, 680), "white")
    pdraw = ImageDraw.Draw(plot)
    pdraw.rounded_rectangle((0, 0, 869, 679), 18, outline="#ced9d3", width=2)
    xs = np.asarray([row["x"] for row in samples], dtype=float)
    ys = np.asarray([row["y"] for row in samples], dtype=float)
    px = 90 + (xs - xs.min()) / max(np.ptp(xs), 1e-6) * 690
    py = 560 - (ys - ys.min()) / max(np.ptp(ys), 1e-6) * 430
    points = list(zip(px.tolist(), py.tolist()))
    pdraw.line(points, fill="#159261", width=9)
    for index, point in enumerate(points):
        color = "#e08b24" if index in (0, len(points) - 1) else "#159261"
        pdraw.ellipse((point[0] - 9, point[1] - 9, point[0] + 9, point[1] + 9), fill=color, outline="white", width=3)
    pdraw.text((48, 32), "Estimated camera trajectory (relative coordinates)", font=font(24, True), fill="#073f30")
    pdraw.text((48, 620), f"Registered images: {data['registered_images']}  |  3D points: {data['points3D']}  |  Confidence: {samples[0]['confidence']:.3f}", font=font(17), fill="#596961")
    image.paste(plot, (980, 190))
    draw.text((980, 910), "หมายเหตุ: VSLAM ให้ตำแหน่งสัมพัทธ์ ส่วนการวางบนแปลนเป็นขั้นตอน Alignment แยกต่างหาก", font=font(19), fill="#8b5a16")
    image.save(OUT / "02-vslam-process.png")


def export_ai_progress():
    image, draw = canvas(
        "AI Progress: โครงสร้าง + สถาปัตย์",
        "ต้นแบบปัจจุบันใช้ภาพจริง + Visual Descriptor + ข้อมูลตามเวลา และส่งค่าความมั่นใจให้คนตรวจทาน",
    )
    source_path = KEYFRAMES / "000060000.jpg"
    source = cv2.imdecode(np.fromfile(source_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    resized = cv2.resize(source, (720, 360), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 60, 160)
    image.paste(fit(source_path, (790, 395)), (65, 185))
    edge_rgb = cv2.cvtColor(edges, cv2.COLOR_GRAY2RGB)
    edge_image = Image.fromarray(edge_rgb).resize((360, 260))
    image.paste(edge_image, (1010, 205))
    draw.text((1010, 485), "Edge / texture evidence", font=font(18, True), fill="#073f30")
    hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [2], None, [32], [0, 256]).reshape(-1)
    hist = hist / max(hist.max(), 1)
    for index, value in enumerate(hist):
        x = 1440 + index * 11
        draw.rectangle((x, 455 - int(value * 220), x + 8, 455), fill="#45a97b")
    draw.text((1440, 485), "Brightness histogram", font=font(18, True), fill="#073f30")
    steps = [
        ("1", "Keyframe 360", "ภาพหลักฐานจริงตามเวลา"),
        ("2", "Visual Feature", "สี แสง texture และ edge"),
        ("3", "Temporal Model", "เรียนรู้แนวโน้มจากวันพัฒนา"),
        ("4", "AI 0–100%", "พร้อม confidence / review"),
    ]
    for index, (number, heading, detail) in enumerate(steps):
        x = 70 + index * 455
        draw.rounded_rectangle((x, 670, x + 390, 880), 18, fill="white", outline="#cbd9d2", width=2)
        draw.ellipse((x + 24, 700, x + 84, 760), fill="#073f30")
        draw.text((x + 44, 712), number, font=font(23, True), fill="white", anchor="ma")
        draw.text((x + 105, 700), heading, font=font(24, True), fill="#073f30")
        draw.text((x + 30, 785), detail, font=font(17), fill="#596961")
        if index < 3:
            draw.polygon([(x + 437, 765), (x + 407, 745), (x + 407, 785)], fill="#159261")
    draw.text((70, 965), "รายการงาน: ฐานราก · เสา · คาน · พื้น · บันได · ผนังโครงสร้าง · ก่อ · ฉาบ · ฝ้า · พื้น · สี · ประตู/หน้าต่าง · ราว · สุขภัณฑ์ · งานภายนอก", font=font(19, True), fill="#073f30")
    draw.text((70, 1015), "ข้อจำกัดที่รายงานตรงไปตรงมา: หากข้อมูล Human Ground Truth < 3 วัน ระบบจะแสดง NOT_TRAINED ไม่แสดงผลมั่ว", font=font(18), fill="#8b5a16")
    image.save(OUT / "03-ai-progress-process.png")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    export_keyframes()
    export_vslam()
    export_ai_progress()
    print(OUT)


if __name__ == "__main__":
    main()
