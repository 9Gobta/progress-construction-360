from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from urllib.parse import urlparse

import boto3
from botocore.client import BaseClient
from botocore.config import Config
from botocore.exceptions import ClientError

from progress_api.config import get_settings

EXTERNAL_MEDIA_BUCKET = "local-external"
CAPTURE_DATE_PATTERN = re.compile(r"(?<!\d)(20\d{6})(?!\d)")


@dataclass(frozen=True)
class LocalStorageStatus:
    path: str
    total_bytes: int
    free_bytes: int
    minimum_free_bytes: int


def external_media_paths() -> list[Path]:
    settings = get_settings()
    configured = [settings.external_media_root]
    if settings.external_media_roots:
        configured.extend(settings.external_media_roots.split(";"))
    roots: list[Path] = []
    for value in configured:
        if not value or not value.strip():
            continue
        root = Path(value.strip()).expanduser().resolve()
        if root not in roots:
            roots.append(root)
    return roots


def _local_guard_path() -> Path | None:
    settings = get_settings()
    configured = settings.processing_temp_dir or settings.storage_guard_path
    if configured:
        return Path(configured).expanduser()

    # Test suites use temporary databases and mocked object storage; never bind
    # their upload assertions to the developer machine's real free space.
    if "PYTEST_CURRENT_TEST" in os.environ:
        return None

    # The development MinIO volume and Python temporary directory both consume
    # the Windows system drive through Docker Desktop. Infer it only for the
    # local endpoint; cloud S3 providers must not be guarded by this disk.
    hostname = (urlparse(settings.s3_endpoint_url).hostname or "").lower()
    if os.name == "nt" and hostname in {"localhost", "127.0.0.1", "::1"}:
        return Path(f"{os.environ.get('SystemDrive', 'C:')}\\")
    return None


def local_storage_status() -> LocalStorageStatus | None:
    settings = get_settings()
    path = _local_guard_path()
    if path is None:
        return None
    try:
        path.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    return LocalStorageStatus(
        path=str(path),
        total_bytes=usage.total,
        free_bytes=usage.free,
        minimum_free_bytes=int(settings.storage_min_free_gb * 1024**3),
    )


def upload_capacity(*, file_size_bytes: int) -> tuple[bool, int, LocalStorageStatus | None]:
    settings = get_settings()
    disk = local_storage_status()
    workspace_bytes = int(file_size_bytes * settings.processing_workspace_factor)
    required_free_bytes = workspace_bytes + int(settings.storage_min_free_gb * 1024**3)
    return disk is None or disk.free_bytes >= required_free_bytes, required_free_bytes, disk


def get_s3_client() -> BaseClient:
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        config=Config(signature_version="s3v4"),
    )


def download_media_file(*, bucket: str, key: str, destination: str) -> None:
    """Download an S3 object or copy a read-only linked local source video."""
    if bucket != EXTERNAL_MEDIA_BUCKET:
        download_object(key=key, destination=destination)
        return

    roots = external_media_paths()
    if not roots:
        raise FileNotFoundError("EXTERNAL_MEDIA_ROOT or EXTERNAL_MEDIA_ROOTS is not configured")
    candidates = [(root / Path(key)).resolve() for root in roots]
    if any(
        not candidate.is_relative_to(root)
        for root, candidate in zip(roots, candidates, strict=True)
    ):
        raise ValueError("External media path escapes configured roots")
    existing = [candidate for candidate in candidates if candidate.is_file()]
    if len(existing) == 1:
        source = existing[0]
    elif len(existing) > 1:
        raise FileNotFoundError(
            f"External source path is ambiguous across {len(existing)} roots: {key}"
        )
    else:
        # External SSD folders may be reorganized after import, and old records
        # can contain a damaged non-ASCII filename.  The capture date embedded
        # by Insta360 remains stable, so recover only when it identifies one
        # unambiguous video.  Never guess between multiple candidate files.
        date_match = CAPTURE_DATE_PATTERN.search(key)
        recovered = (
            [
                candidate.resolve()
                for root in roots
                if root.is_dir()
                # Some field exports prepend a camera/lens sequence number
                # (for example ``120260125 floor1.mp4``), while the imported
                # object key starts at the capture date. Match the stable date
                # anywhere in the filename, but retain the existing
                # unambiguous-single-candidate safety gate below.
                for candidate in root.rglob(f"*{date_match.group(1)}*.mp4")
            ]
            if date_match
            else []
        )
        recovered = [candidate for candidate in recovered if candidate.is_file()]
        if len(recovered) == 1:
            source = recovered[0]
        else:
            detail = (
                f"; recovery candidates={len(recovered)}"
                if date_match
                else ""
            )
            raise FileNotFoundError(
                f"External source video was not found in configured roots: {key}{detail}"
            )
    Path(destination).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def ensure_bucket(client: BaseClient, bucket: str) -> None:
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError:
        client.create_bucket(Bucket=bucket)


def put_object(*, key: str, body: bytes | BinaryIO, content_type: str) -> None:
    settings = get_settings()
    client = get_s3_client()
    ensure_bucket(client, settings.s3_bucket)
    client.put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=body,
        ContentType=content_type,
    )


def delete_object(*, key: str) -> None:
    settings = get_settings()
    get_s3_client().delete_object(Bucket=settings.s3_bucket, Key=key)


def create_multipart_upload(*, key: str, content_type: str) -> str:
    settings = get_settings()
    client = get_s3_client()
    ensure_bucket(client, settings.s3_bucket)
    response = client.create_multipart_upload(
        Bucket=settings.s3_bucket,
        Key=key,
        ContentType=content_type,
    )
    return str(response["UploadId"])


def presign_upload_part(*, key: str, upload_id: str, part_number: int) -> str:
    settings = get_settings()
    return str(
        get_s3_client().generate_presigned_url(
            "upload_part",
            Params={
                "Bucket": settings.s3_bucket,
                "Key": key,
                "UploadId": upload_id,
                "PartNumber": part_number,
            },
            ExpiresIn=3600,
            HttpMethod="PUT",
        )
    )


def list_multipart_parts(*, key: str, upload_id: str) -> list[dict[str, object]]:
    settings = get_settings()
    client = get_s3_client()
    parts: list[dict[str, object]] = []
    marker = 0
    while True:
        response = client.list_parts(
            Bucket=settings.s3_bucket,
            Key=key,
            UploadId=upload_id,
            PartNumberMarker=marker,
        )
        parts.extend(response.get("Parts", []))
        if not response.get("IsTruncated"):
            return parts
        marker = int(response["NextPartNumberMarker"])


def complete_multipart_upload(
    *, key: str, upload_id: str, parts: list[dict[str, object]]
) -> None:
    settings = get_settings()
    get_s3_client().complete_multipart_upload(
        Bucket=settings.s3_bucket,
        Key=key,
        UploadId=upload_id,
        MultipartUpload={"Parts": parts},
    )


def abort_multipart_upload(*, key: str, upload_id: str) -> None:
    settings = get_settings()
    get_s3_client().abort_multipart_upload(
        Bucket=settings.s3_bucket,
        Key=key,
        UploadId=upload_id,
    )


def object_size(*, key: str) -> int:
    settings = get_settings()
    response = get_s3_client().head_object(Bucket=settings.s3_bucket, Key=key)
    return int(response["ContentLength"])


def download_object(*, key: str, destination: str) -> None:
    settings = get_settings()
    get_s3_client().download_file(settings.s3_bucket, key, destination)


def upload_file(*, key: str, source: str, content_type: str) -> None:
    settings = get_settings()
    client = get_s3_client()
    ensure_bucket(client, settings.s3_bucket)
    client.upload_file(
        source,
        settings.s3_bucket,
        key,
        ExtraArgs={"ContentType": content_type},
    )


def presign_get_object(*, key: str, expires_in: int = 3600) -> str:
    settings = get_settings()
    return str(
        get_s3_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.s3_bucket, "Key": key},
            ExpiresIn=expires_in,
            HttpMethod="GET",
        )
    )
