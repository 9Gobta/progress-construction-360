"""Create presentation videos from the project's real processing artifacts.

The clips intentionally keep the two source captures separate:
- 16/06/2026: real keyframe extraction and the current SfM/VSLAM result.
- 23/12/2025: real beam-progress predictions already stored by the system.

No synthetic camera path or synthetic AI score is produced here.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import boto3
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "presentation-assets"
KEYFRAMES = ROOT / ".tmp" / "capture-84e18039-all-keyframes"
FACES = ROOT / ".tmp" / "capture-84e18039-sfm" / "faces"
PATH_JSON = ROOT / "Data" / "derived" / "capture-84e18039-sfm-path.json"
DEC23_OBJECT_PREFIX = (
    "projects/c2ade70f-f813-42fa-9a84-050cb5bb0822/captures/"
    "ac3c0eca-b763-4fcf-b348-d30348e895f0/keyframes"
)
TEMP = Path("C:/ProgressConstructionData/temp/actual-processing-videos")
FONT = Path("C:/Windows/Fonts/tahoma.ttf")
FONT_BOLD = Path("C:/Windows/Fonts/tahomabd.ttf")
WIDTH, HEIGHT, FPS = 1920, 1080, 24


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_BOLD if bold else FONT), size)


def fit_image(path: Path, size: tuple[int, int]) -> Image.Image:
    image = Image.open(path).convert("RGB")
    image.thumbnail(size, Image.Resampling.LANCZOS)
    result = Image.new("RGB", size, "#101813")
    result.paste(image, ((size[0] - image.width) // 2, (size[1] - image.height) // 2))
    return result


def download_ai_evidence(name: str) -> Path:
    """Download through the S3 API because the MinIO volume is encrypted."""
    destination = TEMP / "ai-evidence" / name
    if destination.is_file() and destination.stat().st_size > 0:
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    client = boto3.client(
        "s3",
        endpoint_url="http://localhost:9000",
        aws_access_key_id="progress",
        aws_secret_access_key="change-this-minio-password",
        region_name="us-east-1",
    )
    client.download_file(
        "progress-construction", f"{DEC23_OBJECT_PREFIX}/{name}", str(destination)
    )
    return destination


def base_frame(title: str, subtitle: str, step: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (WIDTH, HEIGHT), "#f3f6f4")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, WIDTH, 132), fill="#073f30")
    draw.text((64, 28), title, font=font(39, True), fill="white")
    draw.text((66, 84), subtitle, font=font(20), fill="#bfe1d4")
    draw.rounded_rectangle((1650, 34, 1850, 96), 16, fill="#159261")
    draw.text((1750, 65), step, font=font(21, True), fill="white", anchor="mm")
    return image, draw


def cv_frame(image: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)


def open_writer(path: Path) -> cv2.VideoWriter:
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (WIDTH, HEIGHT)
    )
    if not writer.isOpened():
        raise RuntimeError(f"Cannot open video writer: {path}")
    return writer


def write_hold(writer: cv2.VideoWriter, image: Image.Image, frames: int) -> None:
    frame = cv_frame(image)
    for _ in range(frames):
        writer.write(frame)


def export_keyframe_clip(raw_path: Path) -> Path:
    files = sorted(KEYFRAMES.glob("*.jpg"))
    if len(files) != 222:
        raise RuntimeError(f"Expected 222 real keyframes, found {len(files)}")
    writer = open_writer(raw_path)
    sample_indexes = np.linspace(0, len(files) - 1, 96).astype(int)
    for shown, source_index in enumerate(sample_indexes, start=1):
        timestamp = source_index * 0.5
        image, draw = base_frame(
            "ดึง Keyframe จากวิดีโอ 360 จริง",
            "Capture 16/6/2569 • MP4 Equirectangular 7680×3840 • sampling ทุก 0.5 วินาที",
            "1 / 3",
        )
        image.paste(fit_image(files[source_index], (1470, 730)), (58, 175))
        draw.rounded_rectangle((1570, 184, 1860, 900), 22, fill="white", outline="#ccd8d2", width=3)
        draw.text((1610, 225), "FFmpeg extraction", font=font(24, True), fill="#073f30")
        draw.text((1610, 286), f"เวลา       {timestamp:05.1f} s", font=font(23), fill="#26352e")
        draw.text((1610, 338), f"ภาพที่      {source_index + 1:03d}/222", font=font(23), fill="#26352e")
        draw.text((1610, 390), "ขนาด       7680×3840", font=font(23), fill="#26352e")
        draw.text((1610, 442), "สถานะ      เขียน JPEG", font=font(23), fill="#159261")
        progress = shown / len(sample_indexes)
        draw.rounded_rectangle((1610, 515, 1820, 545), 15, fill="#dce8e2")
        draw.rounded_rectangle((1610, 515, 1610 + int(210 * progress), 545), 15, fill="#159261")
        draw.text((1715, 584), f"{progress * 100:05.1f}%", font=font(30, True), fill="#073f30", anchor="mm")
        draw.text((64, 986), "ผลจริง: ได้ panorama keyframe 222 ภาพ จากวิดีโอ 111.1 วินาที", font=font(24, True), fill="#073f30")
        writer.write(cv_frame(image))
    writer.release()
    return raw_path


def orb_preview(path: Path) -> Image.Image:
    source = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    orb = cv2.ORB_create(nfeatures=500)
    keypoints = orb.detect(source, None)
    rendered = cv2.drawKeypoints(source, keypoints, None, color=(57, 194, 126))
    rendered = cv2.cvtColor(rendered, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rendered)


def draw_trajectory(draw: ImageDraw.ImageDraw, samples: list[dict], count: int) -> None:
    box = (1030, 210, 1845, 825)
    draw.rounded_rectangle(box, 22, fill="white", outline="#ccd8d2", width=3)
    draw.text((1080, 247), "Estimated camera trajectory", font=font(27, True), fill="#073f30")
    xs = np.asarray([row["x"] for row in samples], dtype=float)
    ys = np.asarray([row["y"] for row in samples], dtype=float)
    px = 1110 + (xs - xs.min()) / max(np.ptp(xs), 1e-6) * 640
    py = 720 - (ys - ys.min()) / max(np.ptp(ys), 1e-6) * 360
    points = list(zip(px.tolist(), py.tolist()))[: max(1, count)]
    if len(points) > 1:
        draw.line(points, fill="#159261", width=10)
    for index, (x, y) in enumerate(points):
        color = "#e08b24" if index in (0, len(points) - 1) else "#159261"
        draw.ellipse((x - 10, y - 10, x + 10, y + 10), fill=color, outline="white", width=3)
    draw.text((1080, 770), f"Registered {min(count, 15)}/222 frames", font=font(21, True), fill="#8c371f")


def export_vslam_clip(raw_path: Path) -> Path:
    data = json.loads(PATH_JSON.read_text(encoding="utf-8"))
    samples = data["samples"]
    face_files = [FACES / f"0000_{index}_0.jpg" for index in range(4)]
    face_previews = [orb_preview(path) for path in face_files]
    writer = open_writer(raw_path)
    total_frames = 144
    for frame_index in range(total_frames):
        progress = frame_index / (total_frames - 1)
        image, draw = base_frame(
            "VSLAM / Structure-from-Motion ที่รันจริง",
            "Capture 16/6/2569 • panorama → cubemap → ORB feature → camera pose",
            "2 / 3",
        )
        for index, preview in enumerate(face_previews):
            tile = preview.copy()
            tile.thumbnail((430, 290), Image.Resampling.LANCZOS)
            x = 55 + (index % 2) * 465
            y = 185 + (index // 2) * 325
            image.paste(tile, (x, y))
            draw.text((x, y + 294), f"Cubemap face {index + 1} + ORB", font=font(18, True), fill="#073f30")
        visible = 1 + int(progress * (len(samples) - 1))
        draw_trajectory(draw, samples, visible)
        draw.rounded_rectangle((1030, 855, 1845, 960), 16, fill="#fff1dd", outline="#e4b873", width=2)
        draw.text((1060, 875), "ผลจริงของรอบนี้", font=font(21, True), fill="#8b5a16")
        draw.text((1060, 918), f"ลงทะเบียนได้ {data['registered_images']}/222 ภาพ • จุด 3D {data['points3D']} จุด • confidence 22.5%", font=font(20), fill="#8b5a16")
        draw.text((62, 1011), "คำเตือน: การติดตามขาดหลังประมาณ 14 วินาที จึงยังไม่ควรใช้เส้นทางนี้เป็น Ground Truth", font=font(23, True), fill="#8c371f")
        writer.write(cv_frame(image))
    writer.release()
    return raw_path


AI_RESULTS = [
    ("000000.jpg", 0.0, 28.558, 64.702),
    ("000002.jpg", 1.0, 28.558, 64.023),
    ("000143.jpg", 71.5, 18.590, 78.694),
    ("000150.jpg", 75.0, 17.981, 75.354),
    ("000154.jpg", 77.0, 29.776, 72.817),
]


def visual_features(path: Path) -> tuple[Image.Image, Image.Image]:
    source = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    small = cv2.resize(source, (760, 380), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 60, 160)
    edges = cv2.cvtColor(edges, cv2.COLOR_GRAY2RGB)
    return Image.fromarray(cv2.cvtColor(small, cv2.COLOR_BGR2RGB)), Image.fromarray(edges)


def export_ai_clip(raw_path: Path) -> Path:
    writer = open_writer(raw_path)
    features = [(row, *visual_features(download_ai_evidence(row[0]))) for row in AI_RESULTS]
    total_frames = 168
    for frame_index in range(total_frames):
        progress = frame_index / (total_frames - 1)
        result_index = min(int(progress * len(features)), len(features) - 1)
        (name, timestamp, prediction, confidence), source, edges = features[result_index]
        phase = (progress * len(features)) % 1
        image, draw = base_frame(
            "ตรวจสอบ AI Progress ต้นแบบเดิม — พบข้อผิดพลาด",
            "Capture 23/12/2568 • ค่า Progress มาจากแนวโน้มตามวัน ไม่ได้จำแนกคานจากภาพ",
            "3 / 3",
        )
        image.paste(source.resize((930, 465)), (55, 185))
        image.paste(edges.resize((610, 300)), (1030, 185))
        draw.text((1030, 500), "Edge / texture evidence", font=font(21, True), fill="#073f30")
        draw.rounded_rectangle((1030, 555, 1840, 850), 22, fill="white", outline="#ccd8d2", width=3)
        draw.text((1070, 590), f"Evidence: {name}  |  t={timestamp:.1f}s", font=font(22), fill="#26352e")
        draw.text((1070, 655), "ผลที่ระบบเคยแสดง: PARTIAL", font=font(29, True), fill="#e08b24")
        animated_prediction = prediction * min(phase * 3.0, 1.0)
        draw.text((1070, 725), f"Progress {animated_prediction:05.1f}%", font=font(42, True), fill="#8c371f")
        draw.text((1515, 725), f"Visual similarity {confidence:04.1f}%", font=font(22, True), fill="#8b5a16")
        draw.rounded_rectangle((1070, 790, 1775, 820), 15, fill="#dce8e2")
        draw.rounded_rectangle((1070, 790, 1070 + int(705 * prediction / 100), 820), 15, fill="#159261")
        draw.text((58, 707), "ขั้นตอนจริง", font=font(24, True), fill="#073f30")
        steps = [
            "เลือกภาพใกล้คานจาก Camera Pose",
            "คำนวณสี/แสง/edge ของภาพรวม",
            "Fit เส้นแนวโน้มจากวันที่ Human กรอก",
            "ใช้ Time trend เป็นค่า 0–100%",
        ]
        for index, label in enumerate(steps):
            y = 762 + index * 58
            active = progress >= index / 5
            draw.ellipse((65, y, 101, y + 36), fill="#159261" if active else "#c9d4cf")
            draw.text((82, y + 18), "✓" if active else "·", font=font(22, True), fill="white", anchor="mm")
            draw.text((120, y + 3), label, font=font(20, active), fill="#073f30" if active else "#7b8982")
        draw.text((1030, 918), "ค่าเดิม: เฉลี่ย 12.3% • แต่ Ground Truth ของวันนี้ = 0%", font=font(24, True), fill="#8c371f")
        draw.text((58, 1020), "สรุปการตรวจสอบ: ผลนี้ INVALID — มี future-data leakage และภาพไม่ได้ใช้ทำนาย Progress โดยตรง", font=font(22, True), fill="#8c371f")
        writer.write(cv_frame(image))
    writer.release()
    return raw_path


def transcode(source: Path, destination: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(source),
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(destination),
        ],
        check=True,
    )


def combine(inputs: list[Path], destination: Path) -> None:
    command = ["ffmpeg", "-y", "-loglevel", "error"]
    for source in inputs:
        command.extend(["-i", str(source)])
    command.extend([
        "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[outv]",
        "-map", "[outv]", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(destination),
    ])
    subprocess.run(command, check=True)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    TEMP.mkdir(parents=True, exist_ok=True)
    raw = [
        export_keyframe_clip(TEMP / "keyframes-raw.mp4"),
        export_vslam_clip(TEMP / "vslam-raw.mp4"),
        export_ai_clip(TEMP / "ai-progress-raw.mp4"),
    ]
    encoded = []
    names = [
        "04-keyframe-extraction-actual.mp4",
        "05-vslam-actual.mp4",
        "06-ai-progress-actual.mp4",
    ]
    for source, name in zip(raw, names):
        temporary = TEMP / name
        transcode(source, temporary)
        shutil.copy2(temporary, OUT / name)
        encoded.append(temporary)
    combined = TEMP / "07-full-actual-processing-demo.mp4"
    combine(encoded, combined)
    shutil.copy2(combined, OUT / combined.name)
    print(OUT)


if __name__ == "__main__":
    main()
