from pathlib import Path

import pytest

from progress_api import object_storage


def test_download_external_media_recovers_unique_file_by_capture_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    external_root = tmp_path / "external"
    # Insta360 exports can include a camera/clip prefix before the capture date.
    actual = external_root / "moved" / "120260125 floor1.mp4"
    actual.parent.mkdir(parents=True)
    actual.write_bytes(b"video")
    destination = tmp_path / "work" / "source.mp4"
    monkeypatch.setattr(
        object_storage.get_settings(), "external_media_root", str(external_root)
    )
    monkeypatch.setattr(object_storage.get_settings(), "external_media_roots", None)

    object_storage.download_media_file(
        bucket=object_storage.EXTERNAL_MEDIA_BUCKET,
        key="old/20260125 damaged-name.mp4",
        destination=str(destination),
    )

    assert destination.read_bytes() == b"video"


def test_download_external_media_does_not_guess_between_duplicate_dates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    external_root = tmp_path / "external"
    for folder in ("a", "b"):
        candidate = external_root / folder / "20260125 floor1.mp4"
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_bytes(folder.encode())
    monkeypatch.setattr(
        object_storage.get_settings(), "external_media_root", str(external_root)
    )
    monkeypatch.setattr(object_storage.get_settings(), "external_media_roots", None)

    with pytest.raises(FileNotFoundError, match="recovery candidates=2"):
        object_storage.download_media_file(
            bucket=object_storage.EXTERNAL_MEDIA_BUCKET,
            key="old/20260125 damaged-name.mp4",
            destination=str(tmp_path / "source.mp4"),
        )


def test_download_external_media_from_additional_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old_root = tmp_path / "old-drive"
    new_root = tmp_path / "new-drive"
    source = new_root / "260616" / "20260616 floor1.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"new-drive-video")
    destination = tmp_path / "work" / "source.mp4"
    monkeypatch.setattr(object_storage.get_settings(), "external_media_root", str(old_root))
    monkeypatch.setattr(object_storage.get_settings(), "external_media_roots", str(new_root))

    object_storage.download_media_file(
        bucket=object_storage.EXTERNAL_MEDIA_BUCKET,
        key="260616/20260616 floor1.mp4",
        destination=str(destination),
    )

    assert destination.read_bytes() == b"new-drive-video"
