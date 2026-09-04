from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from progress_api.config import get_settings

logger = logging.getLogger(__name__)


def temporary_workspace(*, prefix: str) -> tempfile.TemporaryDirectory[str]:
    """Create an auto-cleaned processing directory on the configured drive."""
    configured = get_settings().processing_temp_dir
    parent: str | None = None
    if configured:
        path = Path(configured).expanduser().resolve()
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning(
                "Cannot use configured processing temp directory %s; "
                "falling back to the operating-system temp directory: %s",
                path,
                exc,
            )
        else:
            parent = str(path)
    # Docker/FFmpeg can release bind-mounted files a fraction later on Windows.
    # Cleanup must never turn an otherwise successful processing job into FAILED.
    return tempfile.TemporaryDirectory(
        prefix=prefix,
        dir=parent,
        ignore_cleanup_errors=True,
    )
