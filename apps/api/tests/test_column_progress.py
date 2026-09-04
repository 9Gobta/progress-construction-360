import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from progress_api.models import StructuralElement


def test_column_progress_is_individual_and_separate_from_beams(
    client: TestClient,
    auth_headers: dict[str, str],
    testing_session: sessionmaker[Session],
) -> None:
    project_response = client.post(
        "/api/v1/projects",
        headers=auth_headers,
        json={"name": "Column progress", "timezone": "Asia/Bangkok"},
    )
    assert project_response.status_code == 201
    project_id = project_response.json()["id"]
    floor = client.post(
        f"/api/v1/projects/{project_id}/floors",
        headers=auth_headers,
        json={"name": "ชั้น 1", "level_index": 1},
    ).json()
    media = client.post(
        f"/api/v1/projects/{project_id}/media",
        headers=auth_headers,
        json={
            "original_filename": "column-progress.mp4",
            "content_type": "video/mp4",
            "size_bytes": 1024,
        },
    ).json()
    capture = client.post(
        f"/api/v1/projects/{project_id}/captures",
        headers=auth_headers,
        json={
            "source_video_id": media["id"],
            "captured_at": "2026-09-01T10:00:00+07:00",
            "start_floor_id": floor["id"],
            "start_x": 0.2,
            "start_y": 0.4,
        },
    ).json()
    column_ids = [uuid.uuid4(), uuid.uuid4()]
    with testing_session() as db:
        for element_id, x in zip(column_ids, (0.2893, 0.3791), strict=True):
            db.add(
                StructuralElement(
                    id=element_id,
                    project_id=uuid.UUID(project_id),
                    floor_id=uuid.UUID(floor["id"]),
                    sheet_id=None,
                    ifc_global_id=f"ifc-{element_id.hex[:22]}",
                    ifc_type="IfcColumn",
                    ifc_storey="ชั้น 1",
                    element_kind="COLUMN",
                    code="เสา C1 · legacy-ifc-suffix",
                    name="Column",
                    geometry_json={
                        "footprint": [
                            [x - 0.002, 0.2709],
                            [x + 0.002, 0.2709],
                            [x + 0.002, 0.2749],
                            [x - 0.002, 0.2749],
                        ]
                    },
                    source="IFC_PLAN_ALIGNED",
                )
            )
        db.commit()

    url = f"/api/v1/projects/{project_id}/captures/{capture['id']}/column-progress"
    initial = client.get(url, headers=auth_headers, params={"floor_id": floor["id"]})
    assert initial.status_code == 200
    assert initial.json()["column_count"] == 2
    assert [item["grid_label"] for item in initial.json()["items"]] == ["A/2", "A/3"]

    saved = client.put(
        url,
        headers=auth_headers,
        json={
            "floor_id": floor["id"],
            "entries": [{
                "structural_element_id": str(column_ids[0]),
                "completed_stages": ["REBAR", "FORMWORK"],
            }],
        },
    )
    assert saved.status_code == 200
    payload = saved.json()
    assert float(payload["progress_percent"]) == pytest.approx(25)
    assert payload["labeled_count"] == 1
    first = next(
        item for item in payload["items"]
        if item["structural_element_id"] == str(column_ids[0])
    )
    assert float(first["progress_percent"]) == pytest.approx(50)
    assert first["completed_stages"] == ["REBAR", "FORMWORK"]
