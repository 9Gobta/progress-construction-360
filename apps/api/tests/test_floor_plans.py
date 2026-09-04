import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from progress_api.api.routes import spatial


def _project_and_floor(
    client: TestClient, headers: dict[str, str]
) -> tuple[str, str]:
    project = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "Plan upload project", "timezone": "Asia/Bangkok"},
    ).json()
    floor = client.post(
        f"/api/v1/projects/{project['id']}/floors",
        headers=headers,
        json={
            "name": "ชั้น 2",
            "level_index": 2,
            "elevation_m": 3.2,
            "available_from": "2026-06-23",
        },
    ).json()
    return project["id"], floor["id"]


def test_upload_floor_plan_and_list_plan_availability(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id, floor_id = _project_and_floor(client, auth_headers)
    stored: list[tuple[str, str]] = []
    monkeypatch.setattr(
        spatial,
        "put_object",
        lambda *, key, body, content_type: stored.append((key, content_type)),
    )
    monkeypatch.setattr(
        spatial,
        "presign_get_object",
        lambda *, key, expires_in: f"http://storage.test/{key}?ttl={expires_in}",
    )
    success, encoded = cv2.imencode(".png", np.zeros((120, 240, 3), dtype=np.uint8))
    assert success

    response = client.post(
        f"/api/v1/projects/{project_id}/floors/{floor_id}/plan",
        headers=auth_headers,
        files={"file": ("floor-2.png", encoded.tobytes(), "image/png")},
    )

    assert response.status_code == 200
    assert response.json()["has_plan"] is True
    assert [content_type for _key, content_type in stored] == ["image/png", "image/png"]
    floors = client.get(
        f"/api/v1/projects/{project_id}/floors", headers=auth_headers
    ).json()
    assert floors[0]["has_plan"] is True
    assert floors[0]["available_from"] == "2026-06-23"
    plan_url = client.get(
        f"/api/v1/projects/{project_id}/floors/{floor_id}/plan-url",
        headers=auth_headers,
    )
    assert plan_url.status_code == 200
    assert plan_url.json()["url"].startswith("http://storage.test/")
    plan_info = client.get(
        f"/api/v1/projects/{project_id}/floors/{floor_id}/plan-info",
        headers=auth_headers,
    )
    assert plan_info.status_code == 200
    assert plan_info.json()["page_number"] == 1
    assert plan_info.json()["page_count"] == 1


def test_select_page_from_uploaded_pdf_without_reuploading(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id, floor_id = _project_and_floor(client, auth_headers)
    selected_pages: list[int] = []

    def fake_preview(
        data: bytes,
        content_type: str,
        filename: str,
        page_number: int = 1,
    ) -> tuple[bytes, int, int, int]:
        selected_pages.append(page_number)
        return b"preview", 1200, 800, 7

    monkeypatch.setattr(spatial, "_plan_preview", fake_preview)
    monkeypatch.setattr(spatial, "put_object", lambda **_: None)
    monkeypatch.setattr(
        spatial,
        "download_object",
        lambda *, key, destination: open(destination, "wb").write(b"pdf"),
    )
    uploaded = client.post(
        f"/api/v1/projects/{project_id}/floors/{floor_id}/plan",
        headers=auth_headers,
        files={"file": ("structural.pdf", b"pdf", "application/pdf")},
    )
    assert uploaded.status_code == 200

    changed = client.patch(
        f"/api/v1/projects/{project_id}/floors/{floor_id}/plan",
        headers=auth_headers,
        json={"page_number": 4},
    )

    assert changed.status_code == 200
    assert changed.json()["page_number"] == 4
    assert changed.json()["page_count"] == 7
    assert selected_pages == [1, 4]
