import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from progress_api.models import StructuralElement


def _create_capture(
    client: TestClient, headers: dict[str, str], level: int
) -> tuple[dict, dict, dict]:
    project = client.post(
        "/api/v1/projects", headers=headers,
        json={"name": f"Stair progress L{level}", "timezone": "Asia/Bangkok"},
    ).json()
    floor = client.post(
        f"/api/v1/projects/{project['id']}/floors", headers=headers,
        json={"name": f"ชั้น {level}", "level_index": level},
    ).json()
    media = client.post(
        f"/api/v1/projects/{project['id']}/media", headers=headers,
        json={"original_filename": "stairs.mp4", "content_type": "video/mp4", "size_bytes": 1024},
    ).json()
    capture = client.post(
        f"/api/v1/projects/{project['id']}/captures", headers=headers,
        json={
            "source_video_id": media["id"],
            "captured_at": "2026-09-09T10:00:00+07:00",
            "start_floor_id": floor["id"],
            "start_x": 0.2,
            "start_y": 0.4,
        },
    ).json()
    return project, floor, capture


def test_stair_progress_bulk_save_is_scoped_to_floor(
    client: TestClient,
    auth_headers: dict[str, str],
    testing_session: sessionmaker[Session],
) -> None:
    project, floor, capture = _create_capture(client, auth_headers, 3)
    stair_ids = [uuid.uuid4(), uuid.uuid4()]
    with testing_session() as db:
        for index, element_id in enumerate(stair_ids, 1):
            db.add(StructuralElement(
                id=element_id,
                project_id=uuid.UUID(project["id"]),
                floor_id=uuid.UUID(floor["id"]),
                sheet_id=None,
                ifc_global_id=f"PLAN-STAIR-L3-{index}",
                ifc_type="PLAN_STAIR_ZONE",
                ifc_storey="PLAN LEVEL 3",
                element_kind="STAIR",
                code=f"บันได {index}",
                name=f"Stair {index}",
                geometry_json={
                    "footprint": [[0.2, 0.3], [0.3, 0.3], [0.3, 0.4], [0.2, 0.4]],
                },
                source="PLAN_GRID",
            ))
        db.commit()

    url = f"/api/v1/projects/{project['id']}/captures/{capture['id']}/stair-progress"
    saved = client.put(url, headers=auth_headers, json={
        "floor_id": floor["id"],
        "entries": [
            {"structural_element_id": str(stair_ids[0]), "completed_stages": ["SHORING", "REBAR"]},
            {"structural_element_id": str(stair_ids[1]), "completed_stages": ["SHORING"]},
        ],
    })
    assert saved.status_code == 200
    payload = saved.json()
    assert payload["stair_count"] == 2
    assert payload["labeled_count"] == 2
    assert float(payload["progress_percent"]) == pytest.approx(30)
    assert [row["stage"] for row in payload["stage_summaries"]] == [
        "SHORING", "REBAR", "FORMWORK", "CONCRETE", "STRIP_FORM",
    ]
    assert float(payload["stage_summaries"][0]["progress_percent"]) == pytest.approx(100)
    assert float(payload["stage_summaries"][1]["progress_percent"]) == pytest.approx(50)


def test_floor_one_stair_rejects_shoring(
    client: TestClient,
    auth_headers: dict[str, str],
    testing_session: sessionmaker[Session],
) -> None:
    project, floor, capture = _create_capture(client, auth_headers, 1)
    stair_id = uuid.uuid4()
    with testing_session() as db:
        db.add(StructuralElement(
            id=stair_id,
            project_id=uuid.UUID(project["id"]),
            floor_id=uuid.UUID(floor["id"]),
            sheet_id=None,
            ifc_global_id="PLAN-STAIR-L1-1",
            ifc_type="PLAN_STAIR_ZONE",
            ifc_storey="PLAN LEVEL 1",
            element_kind="STAIR",
            code="บันได 1",
            name="Stair 1",
            geometry_json={"footprint": [[0.2, 0.3], [0.3, 0.3], [0.3, 0.4]]},
            source="PLAN_GRID",
        ))
        db.commit()

    url = f"/api/v1/projects/{project['id']}/captures/{capture['id']}/stair-progress"
    response = client.put(url, headers=auth_headers, json={
        "floor_id": floor["id"],
        "entries": [{"structural_element_id": str(stair_id), "completed_stages": ["SHORING"]}],
    })
    assert response.status_code == 422
    assert "ชั้นของบันได" in response.json()["detail"]


def test_stair_shoring_from_one_floor_never_appears_on_another_floor(
    client: TestClient,
    auth_headers: dict[str, str],
    testing_session: sessionmaker[Session],
) -> None:
    project, floor_two, capture_two = _create_capture(client, auth_headers, 2)
    floor_three = client.post(
        f"/api/v1/projects/{project['id']}/floors", headers=auth_headers,
        json={"name": "ชั้น 3", "level_index": 3},
    ).json()
    media_three = client.post(
        f"/api/v1/projects/{project['id']}/media", headers=auth_headers,
        json={
            "original_filename": "stairs-l3.mp4",
            "content_type": "video/mp4",
            "size_bytes": 1024,
        },
    ).json()
    capture_three = client.post(
        f"/api/v1/projects/{project['id']}/captures", headers=auth_headers,
        json={
            "source_video_id": media_three["id"],
            "captured_at": "2026-09-10T10:00:00+07:00",
            "start_floor_id": floor_three["id"],
            "start_x": 0.2,
            "start_y": 0.4,
        },
    ).json()
    stair_two_id = uuid.uuid4()
    stair_three_id = uuid.uuid4()
    with testing_session() as db:
        for element_id, floor, level in (
            (stair_two_id, floor_two, 2),
            (stair_three_id, floor_three, 3),
        ):
            db.add(StructuralElement(
                id=element_id,
                project_id=uuid.UUID(project["id"]),
                floor_id=uuid.UUID(floor["id"]),
                sheet_id=None,
                ifc_global_id=f"PLAN-STAIR-L{level}-ISOLATION",
                ifc_type="PLAN_STAIR_ZONE",
                ifc_storey=f"PLAN LEVEL {level}",
                element_kind="STAIR",
                code=f"บันไดชั้น {level}",
                name=f"Stair level {level}",
                geometry_json={"footprint": [[0.2, 0.3], [0.3, 0.3], [0.3, 0.4]]},
                source="PLAN_GRID",
            ))
        db.commit()

    saved = client.put(
        f"/api/v1/projects/{project['id']}/captures/{capture_two['id']}/stair-progress",
        headers=auth_headers,
        json={
            "floor_id": floor_two["id"],
            "entries": [{
                "structural_element_id": str(stair_two_id),
                "completed_stages": ["SHORING"],
            }],
        },
    )
    assert saved.status_code == 200
    floor_three_result = client.get(
        f"/api/v1/projects/{project['id']}/captures/{capture_three['id']}/stair-progress",
        headers=auth_headers,
        params={"floor_id": floor_three["id"]},
    )
    assert floor_three_result.status_code == 200
    payload = floor_three_result.json()
    assert payload["labeled_count"] == 0
    assert float(payload["progress_percent"]) == 0
    assert payload["items"][0]["completed_stages"] == []
