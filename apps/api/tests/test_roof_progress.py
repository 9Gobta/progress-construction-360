import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from progress_api.models import Activity, ScheduleVersion, StructuralElement, User


def test_roof_progress_saves_selected_elements_and_updates_activity_actual(
    client: TestClient,
    auth_headers: dict[str, str],
    testing_session: sessionmaker[Session],
) -> None:
    project = client.post(
        "/api/v1/projects",
        headers=auth_headers,
        json={"name": "Roof progress", "timezone": "Asia/Bangkok"},
    ).json()
    floor = client.post(
        f"/api/v1/projects/{project['id']}/floors",
        headers=auth_headers,
        json={"name": "หลังคา 1", "level_index": 5},
    ).json()
    media = client.post(
        f"/api/v1/projects/{project['id']}/media",
        headers=auth_headers,
        json={
            "original_filename": "roof-progress.mp4",
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
    element_ids = [uuid.uuid4(), uuid.uuid4()]
    with testing_session() as db:
        user_id = db.scalar(select(User.id))
        schedule = ScheduleVersion(
            project_id=uuid.UUID(project["id"]),
            name="Roof baseline",
            version_no=1,
            source_type="XLSX",
            is_baseline=True,
            imported_by_id=user_id,
            row_count=1,
            checksum="roof-progress-test",
            status="READY",
        )
        db.add(schedule)
        db.flush()
        db.add(Activity(
            schedule_version_id=schedule.id,
            wbs="1.2.5.1",
            name="งานอะเสชั้นหลังคา",
            planned_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
            planned_finish=datetime(2026, 9, 30, tzinfo=timezone.utc),
            is_summary=False,
            source_row_no=1,
        ))
        for index, element_id in enumerate(element_ids, start=1):
            db.add(StructuralElement(
                id=element_id,
                project_id=uuid.UUID(project["id"]),
                floor_id=uuid.UUID(floor["id"]),
                sheet_id=None,
                ifc_global_id=f"roof-{index}",
                ifc_type="REVIEWED_ROOF_PLAN_ELEMENT",
                ifc_storey="หลังคา 1",
                element_kind="ROOF",
                code=f"RA1-{index}",
                name="อะเส",
                geometry_json={
                    "activity_wbs": "1.2.5.1",
                    "line": [[0.2, 0.3 + index * 0.1], [0.6, 0.3 + index * 0.1]],
                },
                source="REVIEWED_ROOF_PLAN",
            ))
        db.commit()

    url = f"/api/v1/projects/{project['id']}/captures/{capture['id']}/roof-progress"
    initial = client.get(url, headers=auth_headers, params={"floor_id": floor["id"]})
    assert initial.status_code == 200
    assert initial.json()["element_count"] == 2
    assert float(initial.json()["progress_percent"]) == 0

    saved = client.put(url, headers=auth_headers, json={
        "floor_id": floor["id"],
        "entries": [{"structural_element_id": str(element_ids[0]), "complete": True}],
    })
    assert saved.status_code == 200
    assert saved.json()["labeled_count"] == 1
    assert float(saved.json()["progress_percent"]) == pytest.approx(50)
    assert saved.json()["items"][0]["complete"] is True

    actual = client.get(
        f"/api/v1/projects/{project['id']}/progress/manual",
        headers=auth_headers,
    )
    assert actual.status_code == 200
    assert actual.json()[0]["activity_wbs"] == "1.2.5.1"
    assert float(actual.json()[0]["progress_percent"]) == pytest.approx(50)

    invalid = client.put(url, headers=auth_headers, json={
        "floor_id": floor["id"],
        "entries": [{"structural_element_id": str(uuid.uuid4()), "complete": True}],
    })
    assert invalid.status_code == 422

def test_roof_quantity_groups_calculate_count_based_progress(
    client: TestClient,
    auth_headers: dict[str, str],
    testing_session: sessionmaker[Session],
) -> None:
    project = client.post(
        "/api/v1/projects",
        headers=auth_headers,
        json={"name": "Roof quantity progress", "timezone": "Asia/Bangkok"},
    ).json()
    floor = client.post(
        f"/api/v1/projects/{project['id']}/floors",
        headers=auth_headers,
        json={"name": "หลังคา 2", "level_index": 6},
    ).json()
    media = client.post(
        f"/api/v1/projects/{project['id']}/media",
        headers=auth_headers,
        json={
            "original_filename": "roof-count.mp4",
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
    element_ids = [uuid.uuid4() for _index in range(4)]
    with testing_session() as db:
        user_id = db.scalar(select(User.id))
        schedule = ScheduleVersion(
            project_id=uuid.UUID(project["id"]),
            name="Roof quantity baseline",
            version_no=1,
            source_type="XLSX",
            is_baseline=True,
            imported_by_id=user_id,
            row_count=1,
            checksum="roof-quantity-test",
            status="READY",
        )
        db.add(schedule)
        db.flush()
        db.add(Activity(
            schedule_version_id=schedule.id,
            wbs="1.2.5.9",
            name="งานแปเหล็กชั้นหลังคา",
            planned_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
            planned_finish=datetime(2026, 9, 30, tzinfo=timezone.utc),
            is_summary=False,
            source_row_no=1,
        ))
        for index, element_id in enumerate(element_ids, start=1):
            db.add(StructuralElement(
                id=element_id,
                project_id=uuid.UUID(project["id"]),
                floor_id=uuid.UUID(floor["id"]),
                sheet_id=None,
                ifc_global_id=f"roof-purlin-group-{index}",
                ifc_type="REVIEWED_ROOF_PLAN_ELEMENT",
                ifc_storey="หลังคา 2",
                element_kind="ROOF",
                code=f"R2-PURLIN-GROUP-{index}",
                name="แปเหล็ก",
                geometry_json={
                    "activity_wbs": "1.2.5.9",
                    "progress_mode": "COUNT",
                    "total_quantity": 5,
                    "lines": [[[0.2, 0.2], [0.6, 0.2]]],
                },
                source="REVIEWED_ROOF_PLAN",
            ))
        db.commit()

    url = f"/api/v1/projects/{project['id']}/captures/{capture['id']}/roof-progress"
    saved = client.put(url, headers=auth_headers, json={
        "floor_id": floor["id"],
        "entries": [{
            "structural_element_id": str(element_ids[0]),
            "completed_quantity": 3,
            "total_quantity": 5,
        }],
    })
    assert saved.status_code == 200
    first = next(
        item for item in saved.json()["items"]
        if item["structural_element_id"] == str(element_ids[0])
    )
    assert first["completed_quantity"] == 3
    assert first["total_quantity"] == 5
    assert float(first["progress_percent"]) == pytest.approx(60)
    assert first["complete"] is False
    assert float(saved.json()["progress_percent"]) == pytest.approx(15)

    completed = client.put(url, headers=auth_headers, json={
        "floor_id": floor["id"],
        "entries": [{
            "structural_element_id": str(element_ids[0]),
            "completed_quantity": 6,
            "total_quantity": 6,
        }],
    })
    assert completed.status_code == 200
    first = next(
        item for item in completed.json()["items"]
        if item["structural_element_id"] == str(element_ids[0])
    )
    assert first["complete"] is True
    assert float(completed.json()["progress_percent"]) == pytest.approx(28.571, abs=0.001)

    invalid = client.put(url, headers=auth_headers, json={
        "floor_id": floor["id"],
        "entries": [{
            "structural_element_id": str(element_ids[1]),
            "completed_quantity": 6,
            "total_quantity": 5,
        }],
    })
    assert invalid.status_code == 422

    deleted = client.request("DELETE", url, headers=auth_headers, json={
        "floor_id": floor["id"],
        "structural_element_ids": [str(element_ids[0])],
    })
    assert deleted.status_code == 200
    deleted_payload = deleted.json()
    deleted_item = next(
        item for item in deleted_payload["items"]
        if item["structural_element_id"] == str(element_ids[0])
    )
    assert deleted_payload["labeled_count"] == 0
    assert float(deleted_payload["progress_percent"]) == 0
    assert deleted_item["progress_percent"] is None
    assert deleted_item["completed_quantity"] == 0
    assert deleted_item["total_quantity"] == 6
    assert deleted_item["capture_id"] is None

    manual = client.get(
        f"/api/v1/projects/{project['id']}/progress/manual",
        headers=auth_headers,
    )
    assert manual.status_code == 200
    assert manual.json() == []

    deleted_again = client.request("DELETE", url, headers=auth_headers, json={
        "floor_id": floor["id"],
        "structural_element_ids": [str(element_ids[0])],
    })
    assert deleted_again.status_code == 404
