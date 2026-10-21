
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_root_returns_running_status() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["status"] == "running"


def test_health_returns_ok() -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["service"] == "FinSentinel"
