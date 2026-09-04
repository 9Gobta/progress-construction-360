from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from progress_api.db import Base, get_db
from progress_api.main import app


@pytest.fixture
def testing_session(tmp_path: Path) -> Generator[sessionmaker[Session], None, None]:
    database_path = tmp_path / "test.db"
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection: object, _: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    yield testing_session

    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client(testing_session: sessionmaker[Session]) -> Generator[TestClient, None, None]:

    def override_get_db() -> Generator[Session, None, None]:
        with testing_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "owner@example.com",
            "display_name": "Project Owner",
            "password": "safe-password-123",
        },
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
