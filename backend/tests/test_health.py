from fastapi.testclient import TestClient

from app.main import create_app


def test_health_reports_ok_and_mock_mode(monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "mock")
    client = TestClient(create_app())
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["agent_mode"] == "mock"
