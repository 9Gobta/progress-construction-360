import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from progress_api.models import Capture, Floor, Keyframe, MediaFile, User


def test_bim_download_requires_membership_and_redirects_to_storage(
    client: TestClient,
    auth_headers: dict[str, str],
    testing_session: sessionmaker[Session],
    monkeypatch,
) -> None:
    from progress_api.api.routes import bim as bim_routes

    project = client.post(
        "/api/v1/projects",
        headers=auth_headers,
        json={"name": "BIM proxy", "timezone": "Asia/Bangkok"},
    ).json()
    with testing_session() as db:
        owner = db.scalar(select(User).where(User.email == "owner@example.com"))
        assert owner is not None
        model = MediaFile(
            id=uuid.uuid4(),
            project_id=uuid.UUID(project["id"]),
            media_kind="BIM_IFC",
            bucket="test-bucket",
            object_key=f"projects/{project['id']}/bim/model.ifc",
            original_filename="model.ifc",
            content_type="application/x-step",
            size_bytes=128,
            upload_status="READY",
            created_by_id=owner.id,
        )
        source = MediaFile(
            id=uuid.uuid4(), project_id=uuid.UUID(project["id"]), media_kind="SOURCE_VIDEO",
            bucket="test-bucket", object_key="source.mp4", original_filename="source.mp4",
            content_type="video/mp4", size_bytes=256, upload_status="READY", created_by_id=owner.id,
        )
        image = MediaFile(
            id=uuid.uuid4(), project_id=uuid.UUID(project["id"]), media_kind="KEYFRAME",
            bucket="test-bucket", object_key="frame.jpg", original_filename="frame.jpg",
            content_type="image/jpeg", size_bytes=64, upload_status="READY", created_by_id=owner.id,
        )
        floor = Floor(project_id=uuid.UUID(project["id"]), name="ชั้น 1", level_index=1)
        db.add_all([model, source, image, floor])
        db.flush()
        capture = Capture(
            project_id=uuid.UUID(project["id"]), source_video_id=source.id,
            captured_at=datetime(2026, 9, 8, tzinfo=timezone.utc), start_floor_id=floor.id,
            start_x=Decimal("0.5"), start_y=Decimal("0.5"), dataset_split="DEVELOPMENT",
            status="READY", created_by_id=owner.id,
        )
        db.add(capture)
        db.flush()
        keyframe = Keyframe(
            capture_id=capture.id, media_file_id=image.id, frame_index=0,
            timestamp_ms=0, quality_status="USABLE", is_warp_point=True,
        )
        db.add(keyframe)
        db.commit()
        model_id = model.id
        keyframe_id = keyframe.id

    monkeypatch.setattr(
        bim_routes,
        "presign_get_object",
        lambda *, key, expires_in: f"https://storage.example/{key}?expires={expires_in}",
    )
    response = client.get(
        f"/api/v1/projects/{project['id']}/bim-models/{model_id}/file",
        headers=auth_headers,
        follow_redirects=False,
    )
    assert response.status_code == 307
    assert response.headers["location"].startswith("https://storage.example/projects/")

    empty = client.get(
        f"/api/v1/projects/{project['id']}/bim-models/{model_id}/viewpoints/{keyframe_id}",
        headers=auth_headers,
    )
    assert empty.status_code == 200
    assert empty.json() is None
    saved = client.put(
        f"/api/v1/projects/{project['id']}/bim-models/{model_id}/viewpoints/{keyframe_id}",
        headers=auth_headers,
        json={
            "position_x": 1.25, "position_y": 2.5, "position_z": -3.75,
            "target_x": 0, "target_y": 1.5, "target_z": 0, "fov": 48,
        },
    )
    assert saved.status_code == 200
    assert saved.json()["keyframe_id"] == str(keyframe_id)
    assert saved.json()["position_z"] == -3.75
    loaded = client.get(
        f"/api/v1/projects/{project['id']}/bim-models/{model_id}/viewpoints/{keyframe_id}",
        headers=auth_headers,
    )
    assert loaded.status_code == 200
    assert loaded.json()["fov"] == 48

    stranger = client.post(
        "/api/v1/auth/register",
        json={
            "email": "bim-stranger@example.com",
            "display_name": "BIM Stranger",
            "password": "another-password-123",
        },
    )
    stranger_headers = {"Authorization": f"Bearer {stranger.json()['access_token']}"}
    hidden = client.get(
        f"/api/v1/projects/{project['id']}/bim-models/{model_id}/file",
        headers=stranger_headers,
        follow_redirects=False,
    )
    assert hidden.status_code == 404
