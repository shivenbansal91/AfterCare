import pytest
from fastapi.testclient import TestClient

from . import store
from .main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA", tmp_path)
    monkeypatch.setenv("AFTERCARE_AUTO_AI", "0")
    client = TestClient(app, base_url="http://127.0.0.1:8000", headers={"Origin": "http://127.0.0.1:5173"})
    client.post("/api/auth/register", json={"username": "test-owner", "password": "fictional-password-123"})
    patient = client.post("/api/care/patients", json={"name": "Fictional patient"}).json()["patients"][0]
    client.post(f"/api/care/patients/{patient['id']}/episodes", json={"title": "Test recovery", "started": "2026-10-17"})
    return client
