from __future__ import annotations

import subprocess
from pathlib import Path

from progress_api.config import get_settings


class Insta360StitchingError(RuntimeError):
    pass


class Insta360StitcherUnavailable(Insta360StitchingError):
    pass


def get_stitcher_executable() -> Path:
    """Return the configured wrapper or fail before downloading a large INSV."""
    configured = get_settings().insta360_stitcher_path
    if not configured:
        raise Insta360StitcherUnavailable(
            "ยังไม่ได้ติดตั้ง Insta360 MediaSDK Stitcher: ตั้งค่า "
            "INSTA360_STITCHER_PATH แล้ว Retry งานนี้"
        )
    executable = Path(configured).expanduser().resolve()
    if not executable.is_file():
        raise Insta360StitcherUnavailable(
            f"ไม่พบ Insta360 Stitcher ที่ {executable}: ตรวจ INSTA360_STITCHER_PATH"
        )
    return executable


def stitch_insv(*, source: Path, destination: Path) -> None:
    """Stitch one X5 INSV file through our licensed MediaSDK CLI wrapper.

    The wrapper is intentionally an external executable: Insta360 distributes
    MediaSDK separately and it cannot be bundled into this repository. Its CLI
    contract is stable so a local RTX worker and a future cloud GPU worker use
    the same application pipeline.
    """
    settings = get_settings()
    executable = get_stitcher_executable()

    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(executable),
        "--input",
        str(source.resolve()),
        "--output",
        str(destination.resolve()),
        "--width",
        "5760",
        "--height",
        "2880",
        "--flowstate",
        "--direction-lock",
    ]
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=settings.insta360_stitch_timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise Insta360StitchingError("Insta360 Stitching ใช้เวลานานเกินกำหนด") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc))[-3000:]
        raise Insta360StitchingError(f"Insta360 Stitching ไม่สำเร็จ: {detail}") from exc

    if not destination.is_file() or destination.stat().st_size == 0:
        detail = (result.stderr or result.stdout or "ไม่พบไฟล์ผลลัพธ์")[-3000:]
        raise Insta360StitchingError(f"Stitcher ไม่ได้สร้าง MP4: {detail}")
