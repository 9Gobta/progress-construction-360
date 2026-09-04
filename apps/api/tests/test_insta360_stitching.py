from pathlib import Path
from types import SimpleNamespace

import pytest

from progress_api.services import insta360_stitching


def test_stitch_insv_requires_configured_mediasdk(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        insta360_stitching,
        "get_settings",
        lambda: SimpleNamespace(
            insta360_stitcher_path=None,
            insta360_stitch_timeout_seconds=60,
        ),
    )

    with pytest.raises(insta360_stitching.Insta360StitcherUnavailable):
        insta360_stitching.stitch_insv(
            source=tmp_path / "capture.insv",
            destination=tmp_path / "stitched.mp4",
        )


def test_stitch_insv_uses_wrapper_contract(monkeypatch, tmp_path: Path) -> None:
    executable = tmp_path / "progress-insta360-stitcher.exe"
    executable.write_bytes(b"stub")
    source = tmp_path / "capture.insv"
    source.write_bytes(b"raw")
    destination = tmp_path / "stitched.mp4"
    observed: dict[str, object] = {}

    monkeypatch.setattr(
        insta360_stitching,
        "get_settings",
        lambda: SimpleNamespace(
            insta360_stitcher_path=str(executable),
            insta360_stitch_timeout_seconds=60,
        ),
    )

    def fake_run(command, **kwargs):
        observed["command"] = command
        observed["kwargs"] = kwargs
        destination.write_bytes(b"stitched-video")
        return SimpleNamespace(stdout="ok", stderr="")

    monkeypatch.setattr(insta360_stitching.subprocess, "run", fake_run)

    insta360_stitching.stitch_insv(source=source, destination=destination)

    command = observed["command"]
    assert command[0] == str(executable.resolve())
    assert command[command.index("--input") + 1] == str(source.resolve())
    assert command[command.index("--output") + 1] == str(destination.resolve())
    assert "--flowstate" in command
    assert "--direction-lock" in command
