import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from progress_api.models import StructuralElement


def test_s1_and_pc1_use_their_own_stage_workflows(
    client: TestClient,
    auth_headers: dict[str, str],
    testing_session: sessionmaker[Session],
) -> None:
    project = client.post(
        "/api/v1/projects",
        headers=auth_headers,
        json={"name": "Slab progress", "timezone": "Asia/Bangkok"},
    ).json()
    floor = client.post(
        f"/api/v1/projects/{project['id']}/floors",
        headers=auth_headers,
        json={"name": "ชั้น 2", "level_index": 2},
    ).json()
    media = client.post(
        f"/api/v1/projects/{project['id']}/media",
        headers=auth_headers,
        json={
            "original_filename": "slab-progress.mp4",
            "content_type": "video/mp4",
            "size_bytes": 1024,
        },
    ).json()
    capture = client.post(
        f"/api/v1/projects/{project['id']}/captures",
        headers=auth_headers,
        json={
            "source_video_id": media["id"],
            "captured_at": "2026-09-01T10:00:00+07:00",
            "start_floor_id": floor["id"],
            "start_x": 0.2,
            "start_y": 0.4,
        },
    ).json()
    ids = {"S1": uuid.uuid4(), "PC1": uuid.uuid4()}
    with testing_session() as db:
        for index, (slab_type, element_id) in enumerate(ids.items()):
            db.add(StructuralElement(
                id=element_id,
                project_id=uuid.UUID(project["id"]),
                floor_id=uuid.UUID(floor["id"]),
                sheet_id=None,
                ifc_global_id=f"PLAN-SLAB-L2-{slab_type}",
                ifc_type="PLAN_GRID_ZONE",
                ifc_storey="PLAN LEVEL 2",
                element_kind="SLAB",
                code=f"พื้นที่ {slab_type}",
                name=f"Slab {slab_type}",
                geometry_json={
                    "area_m2": 10,
                    "slab_type": slab_type,
                    "footprint": [
                        [0.2 + index * 0.1, 0.3],
                        [0.3 + index * 0.1, 0.3],
                        [0.3 + index * 0.1, 0.4],
                        [0.2 + index * 0.1, 0.4],
                    ],
                },
                source="PLAN_GRID",
            ))
        db.commit()

    url = f"/api/v1/projects/{project['id']}/captures/{capture['id']}/slab-progress"
    saved = client.put(url, headers=auth_headers, json={
        "floor_id": floor["id"],
        "entries": [
            {
                "structural_element_id": str(ids["S1"]),
                "completed_stages": [
                    "SHORING", "REBAR", "FORMWORK", "CONCRETE", "STRIP_FORM",
                ],
            },
            {
                "structural_element_id": str(ids["PC1"]),
                "completed_stages": [
                    "SHORING", "PLACE_PRECAST", "REBAR", "FORMWORK", "CONCRETE",
                ],
            },
        ],
    })
    assert saved.status_code == 200
    payload = saved.json()
    by_type = {item["geometry_json"]["slab_type"]: item for item in payload["items"]}
    assert float(by_type["S1"]["progress_percent"]) == pytest.approx(100)
    assert float(by_type["PC1"]["progress_percent"]) == pytest.approx(83.333, abs=0.001)
    assert float(payload["progress_percent"]) == pytest.approx(90.909, abs=0.001)

    later_media = client.post(
        f"/api/v1/projects/{project['id']}/media",
        headers=auth_headers,
        json={
            "original_filename": "slab-progress-later.mp4",
            "content_type": "video/mp4",
            "size_bytes": 1024,
        },
    ).json()
    later_capture = client.post(
        f"/api/v1/projects/{project['id']}/captures",
        headers=auth_headers,
        json={
            "source_video_id": later_media["id"],
            "captured_at": "2026-09-08T10:00:00+07:00",
            "start_floor_id": floor["id"],
            "start_x": 0.2,
            "start_y": 0.4,
        },
    ).json()
    carried = client.get(
        f"/api/v1/projects/{project['id']}/captures/{later_capture['id']}/slab-progress",
        headers=auth_headers,
        params={"floor_id": floor["id"]},
    )
    assert carried.status_code == 200
    assert carried.json()["labeled_count"] == 2
    assert float(carried.json()["progress_percent"]) == pytest.approx(90.909, abs=0.001)

    invalid = client.put(url, headers=auth_headers, json={
        "floor_id": floor["id"],
        "entries": [{
            "structural_element_id": str(ids["S1"]),
            "completed_stages": ["PLACE_PRECAST"],
        }],
    })
    assert invalid.status_code == 422
    assert "GS/S1/PC1" in invalid.json()["detail"]


def test_floor_one_gs_and_s1_use_reviewed_stage_workflows(
    client: TestClient,
    auth_headers: dict[str, str],
    testing_session: sessionmaker[Session],
) -> None:
    project = client.post(
        "/api/v1/projects",
        headers=auth_headers,
        json={"name": "Floor one slab progress", "timezone": "Asia/Bangkok"},
    ).json()
    floor = client.post(
        f"/api/v1/projects/{project['id']}/floors",
        headers=auth_headers,
        json={"name": "ชั้น 1", "level_index": 1},
    ).json()
    media = client.post(
        f"/api/v1/projects/{project['id']}/media",
        headers=auth_headers,
        json={
            "original_filename": "floor-one.mp4",
            "content_type": "video/mp4",
            "size_bytes": 1024,
        },
    ).json()
    capture = client.post(
        f"/api/v1/projects/{project['id']}/captures",
        headers=auth_headers,
        json={
            "source_video_id": media["id"],
            "captured_at": "2026-09-01T10:00:00+07:00",
            "start_floor_id": floor["id"],
            "start_x": 0.2,
            "start_y": 0.4,
        },
    ).json()
    definitions = {
        "GS": ("GS", "SOIL_COMPACTION", [
            "SOIL_COMPACTION", "REBAR", "FORMWORK", "CONCRETE", "STRIP_FORM",
        ]),
        "S1": ("S1_FLOOR_1", "FORMWORK", [
            "FORMWORK", "REBAR", "CONCRETE", "STRIP_FORM",
        ]),
    }
    ids = {slab_type: uuid.uuid4() for slab_type in definitions}
    with testing_session() as db:
        for index, (slab_type, element_id) in enumerate(ids.items()):
            workflow, _first_stage, _stages = definitions[slab_type]
            db.add(StructuralElement(
                id=element_id,
                project_id=uuid.UUID(project["id"]),
                floor_id=uuid.UUID(floor["id"]),
                sheet_id=None,
                ifc_global_id=f"PLAN-SLAB-L1-{slab_type}",
                ifc_type="PLAN_GRID_ZONE",
                ifc_storey="PLAN LEVEL 1",
                element_kind="SLAB",
                code=f"พื้นที่ {slab_type}",
                name=f"Slab {slab_type}",
                geometry_json={
                    "area_m2": 10,
                    "slab_type": slab_type,
                    "slab_workflow": workflow,
                    "footprint": [
                        [0.2 + index * 0.1, 0.3],
                        [0.3 + index * 0.1, 0.3],
                        [0.3 + index * 0.1, 0.4],
                        [0.2 + index * 0.1, 0.4],
                    ],
                },
                source="PLAN_GRID",
            ))
        db.commit()

    url = f"/api/v1/projects/{project['id']}/captures/{capture['id']}/slab-progress"
    saved = client.put(url, headers=auth_headers, json={
        "floor_id": floor["id"],
        "entries": [
            {
                "structural_element_id": str(ids[slab_type]),
                "completed_stages": stages,
            }
            for slab_type, (_workflow, _first_stage, stages) in definitions.items()
        ],
    })
    assert saved.status_code == 200
    by_type = {
        item["geometry_json"]["slab_type"]: item for item in saved.json()["items"]
    }
    assert float(by_type["GS"]["progress_percent"]) == pytest.approx(100)
    assert float(by_type["S1"]["progress_percent"]) == pytest.approx(100)
    assert float(saved.json()["progress_percent"]) == pytest.approx(100)

    invalid = client.put(url, headers=auth_headers, json={
        "floor_id": floor["id"],
        "entries": [{
            "structural_element_id": str(ids["S1"]),
            "completed_stages": ["SHORING"],
        }],
    })
    assert invalid.status_code == 422
