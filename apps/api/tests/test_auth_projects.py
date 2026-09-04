from fastapi.testclient import TestClient


def test_register_login_and_current_user(client: TestClient) -> None:
    payload = {
        "email": "student@example.com",
        "display_name": "Student",
        "password": "strong-password-123",
    }
    registered = client.post("/api/v1/auth/register", json=payload)
    assert registered.status_code == 201
    token = registered.json()["access_token"]

    duplicate = client.post("/api/v1/auth/register", json=payload)
    assert duplicate.status_code == 409

    logged_in = client.post(
        "/api/v1/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert logged_in.status_code == 200

    current = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert current.status_code == 200
    assert current.json()["email"] == payload["email"]


def test_projects_are_isolated_by_membership(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    created = client.post(
        "/api/v1/projects",
        headers=auth_headers,
        json={
            "name": "อาคารหอพัก ค.ส.ล. 4 ชั้น",
            "location": "ประเทศไทย",
            "timezone": "Asia/Bangkok",
            "description": "โครงการทดลอง",
        },
    )
    assert created.status_code == 201
    project = created.json()
    assert project["role"] == "admin"

    listed = client.get("/api/v1/projects", headers=auth_headers)
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [project["id"]]

    other = client.post(
        "/api/v1/auth/register",
        json={
            "email": "viewer@example.com",
            "display_name": "Viewer",
            "password": "another-password-123",
        },
    )
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    hidden = client.get(f"/api/v1/projects/{project['id']}", headers=other_headers)
    assert hidden.status_code == 404


def test_admin_can_add_reviewer_to_project(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    project = client.post(
        "/api/v1/projects",
        headers=auth_headers,
        json={"name": "Structural inspection", "timezone": "Asia/Bangkok"},
    ).json()
    reviewer = client.post(
        "/api/v1/auth/register",
        json={
            "email": "inspector@example.com",
            "display_name": "Inspector",
            "password": "reviewer-password-123",
        },
    )
    reviewer_headers = {
        "Authorization": f"Bearer {reviewer.json()['access_token']}"
    }

    added = client.post(
        f"/api/v1/projects/{project['id']}/members",
        headers=auth_headers,
        json={"email": "inspector@example.com", "role": "reviewer"},
    )
    assert added.status_code == 201
    assert added.json()["role"] == "reviewer"

    visible = client.get(
        f"/api/v1/projects/{project['id']}", headers=reviewer_headers
    )
    assert visible.status_code == 200
    assert visible.json()["role"] == "reviewer"

    members = client.get(
        f"/api/v1/projects/{project['id']}/members", headers=reviewer_headers
    )
    assert members.status_code == 200
    assert {row["email"] for row in members.json()} == {
        "owner@example.com",
        "inspector@example.com",
    }


def test_project_member_must_register_before_being_added(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    project = client.post(
        "/api/v1/projects",
        headers=auth_headers,
        json={"name": "Structural inspection", "timezone": "Asia/Bangkok"},
    ).json()
    response = client.post(
        f"/api/v1/projects/{project['id']}/members",
        headers=auth_headers,
        json={"email": "missing@example.com", "role": "reviewer"},
    )
    assert response.status_code == 409
