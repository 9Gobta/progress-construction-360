import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from progress_api.models import Capture, Floor, Keyframe, MediaFile, User


def test_field_notes_are_scoped_to_capture_floor_and_keyframe(
    client: TestClient,
    auth_headers: dict[str, str],
    testing_session: sessionmaker[Session],
    monkeypatch,
) -> None:
    from progress_api.api.routes import field_notes as routes

    project = client.post(
        "/api/v1/projects",
        headers=auth_headers,
        json={"name": "Field notes", "timezone": "Asia/Bangkok"},
    ).json()
    with testing_session() as db:
        owner = db.scalar(select(User).where(User.email == "owner@example.com"))
        assert owner is not None
        source = MediaFile(
            project_id=uuid.UUID(project["id"]),
            media_kind="SOURCE_VIDEO",
            bucket="test",
            object_key="source.mp4",
            original_filename="source.mp4",
            content_type="video/mp4",
            size_bytes=100,
            upload_status="READY",
            created_by_id=owner.id,
        )
        image = MediaFile(
            project_id=uuid.UUID(project["id"]),
            media_kind="KEYFRAME",
            bucket="test",
            object_key="frame.jpg",
            original_filename="frame.jpg",
            content_type="image/jpeg",
            size_bytes=50,
            upload_status="READY",
            created_by_id=owner.id,
        )
        floor = Floor(project_id=uuid.UUID(project["id"]), name="ชั้น 3", level_index=3)
        db.add_all([source, image, floor])
        db.flush()
        capture = Capture(
            project_id=uuid.UUID(project["id"]),
            source_video_id=source.id,
            captured_at=datetime(2026, 7, 3, tzinfo=timezone.utc),
            start_floor_id=floor.id,
            start_x=Decimal("0.2"),
            start_y=Decimal("0.3"),
            status="READY",
            created_by_id=owner.id,
        )
        db.add(capture)
        db.flush()
        frame = Keyframe(
            capture_id=capture.id,
            media_file_id=image.id,
            frame_index=0,
            timestamp_ms=0,
            quality_status="USABLE",
            is_warp_point=True,
        )
        db.add(frame)
        db.commit()
        capture_id, floor_id, frame_id = capture.id, floor.id, frame.id

    monkeypatch.setattr(
        routes, "presign_get_object", lambda *, key, expires_in: f"https://test/{key}"
    )
    created = client.post(
        f"/api/v1/projects/{project['id']}/field-notes",
        headers=auth_headers,
        json={
            "capture_id": str(capture_id),
            "floor_id": str(floor_id),
            "keyframe_id": str(frame_id),
            "title": "ตรวจค้ำยัน",
            "description": "จุดทดสอบ",
            "status": "P2",
            "tags": ["ค้ำยัน", "ชั้น 3"],
            "plan_x": 0.2,
            "plan_y": 0.3,
        },
    )
    assert created.status_code == 201, created.text
    note = created.json()
    assert note["floor_name"] == "ชั้น 3"
    assert note["capture_id"] == str(capture_id)
    assert note["tags"] == ["ค้ำยัน", "ชั้น 3"]

    commented = client.post(
        f"/api/v1/projects/{project['id']}/field-notes/{note['id']}/comments",
        headers=auth_headers,
        json={"body": "ตรวจซ้ำแล้ว"},
    )
    assert commented.status_code == 201
    assert commented.json()["comments"][0]["body"] == "ตรวจซ้ำแล้ว"

    updated = client.patch(
        f"/api/v1/projects/{project['id']}/field-notes/{note['id']}",
        headers=auth_headers,
        json={"status": "VERIFIED"},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "VERIFIED"

    marked_up = client.patch(
        f"/api/v1/projects/{project['id']}/field-notes/{note['id']}",
        headers=auth_headers,
        json={"markup_paths": [[[100, 100], [200, 240]]]},
    )
    assert marked_up.status_code == 200
    assert marked_up.json()["markup_paths"] == [[[100.0, 100.0], [200.0, 240.0]]]

    listed = client.get(
        f"/api/v1/projects/{project['id']}/field-notes?floor_id={floor_id}&tag=ค้ำยัน",
        headers=auth_headers,
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [note["id"]]

    uploaded: list[tuple[str, str]] = []
    monkeypatch.setattr(
        routes,
        "upload_file",
        lambda *, key, source, content_type: uploaded.append((key, content_type)),
    )
    attached = client.post(
        f"/api/v1/projects/{project['id']}/field-notes/{note['id']}/attachments",
        headers=auth_headers,
        files={"file": ("evidence.png", b"png-data", "image/png")},
    )
    assert attached.status_code == 201, attached.text
    assert attached.json()["attachments"][0]["filename"] == "evidence.png"
    assert uploaded[0][1] == "image/png"

    invalid = client.post(
        f"/api/v1/projects/{project['id']}/field-notes",
        headers=auth_headers,
        json={
            "capture_id": str(capture_id),
            "floor_id": str(uuid.uuid4()),
            "keyframe_id": str(frame_id),
            "title": "ผิดชั้น",
        },
    )
    assert invalid.status_code == 404
