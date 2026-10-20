import hashlib
import time

from fastapi.testclient import TestClient

from . import store
from .main import app


def other_client():
    return TestClient(app, base_url="http://127.0.0.1:8000", headers={"Origin": "http://127.0.0.1:5173"})


def test_signed_out_and_revoked_sessions_cannot_read_documents(client):
    report = client.post("/api/reports/sample").json()
    original_cookie = client.cookies.get("aftercare_session")
    assert client.post("/api/auth/logout").status_code == 200
    for path in ["/api/care", "/api/reports", f"/api/reports/{report['id']}/file", f"/api/reports/{report['id']}/pages/0"]:
        assert client.get(path).status_code == 401
    client.cookies.set("aftercare_session", original_cookie)
    assert client.get("/api/reports").status_code == 401


def test_another_account_cannot_read_or_modify_any_report_surface(client):
    report = client.post("/api/reports/sample").json()
    field = report["fields"][0]
    visitor = other_client()
    assert visitor.post("/api/auth/register", json={"username": "second", "password": "another-password-123"}).status_code == 201
    assert visitor.get("/api/reports").json() == []
    prefix = f"/api/reports/{report['id']}"
    for path in ["", "/file", "/pages/0", "/plan", "/history", "/activity"]:
        assert visitor.get(prefix + path).status_code == 404
    assert visitor.patch(f"{prefix}/fields/{field['id']}", json={"value": "changed", "status": "confirmed"}).status_code == 404
    assert visitor.post(f"{prefix}/plan").status_code == 404
    assert visitor.post(f"{prefix}/medications/log", json={"request_id": "b0fb2542-564d-4141-a7ad-bd34d6ca7e48", "group": "Medication 1", "status": "taken"}).status_code == 404
    assert visitor.post(f"{prefix}/medications/log/missing/undo").status_code == 404
    assert visitor.put(f"{prefix}/visits/{field['id']}", json={"status": "completed"}).status_code == 404
    assert client.get(prefix).json()["fields"][0]["value"] == field["value"]


def test_patient_episode_and_contact_ownership(client):
    first = client.get("/api/care").json()["patients"][0]
    episode = first["episodes"][0]
    other = other_client()
    other.post("/api/auth/register", json={"username": "visitor", "password": "visitor-password-123"})
    assert other.post(f"/api/care/patients/{first['id']}/episodes", json={"title": "Stolen", "started": "2026-10-17"}).status_code == 404
    assert other.post(f"/api/reports/sample?episode_id={episode['id']}").status_code == 404
    body = {"name": "Fictional sister", "role": "Family", "phone": "+91 98765 43210", "note": "Call after 6"}
    result = client.post(f"/api/care/patients/{first['id']}/contacts", json=body)
    assert result.status_code == 201
    contact = result.json()["patients"][0]["contacts"][0]
    assert other.post(f"/api/care/patients/{first['id']}/contacts", json=body).status_code == 404
    assert other.delete(f"/api/care/patients/{first['id']}/contacts/{contact['id']}").status_code == 404
    second = client.post("/api/care/patients", json={"name": "Another fictional patient"}).json()["patients"][1]
    assert second["contacts"] == []
    assert client.delete(f"/api/care/patients/{second['id']}/contacts/{contact['id']}").status_code == 404
    assert client.delete(f"/api/care/patients/{first['id']}/contacts/{contact['id']}").status_code == 200


def test_reports_default_to_personal_space_and_allow_existing_context(client):
    patient = client.get("/api/care").json()["patients"][0]
    client.post(f"/api/care/patients/{patient['id']}/episodes", json={"title": "Second recovery", "started": "2026-11-01"})
    personal = client.post("/api/care/personal").json()["personal"]
    report = client.post("/api/reports/sample").json()
    assert report["episode_id"] == personal["episode_id"]
    report = client.post(f"/api/reports/sample?episode_id={patient['episodes'][0]['id']}").json()
    assert report["episode_id"] == patient["episodes"][0]["id"]


def test_legacy_import_is_explicit_and_first_account_only(client):
    report = client.post("/api/reports/sample").json()
    with store.connect() as db:
        db.execute("DELETE FROM report_access WHERE report_id=?", (report["id"],))
    assert client.get("/api/reports").json() == []
    workspace = client.get("/api/care").json()
    assert workspace["legacy_count"] == 1
    other = other_client()
    other.post("/api/auth/register", json={"username": "another", "password": "another-password-123"})
    p = other.post("/api/care/patients", json={"name": "Other"}).json()["patients"][0]
    p = other.post(f"/api/care/patients/{p['id']}/episodes", json={"title": "Recovery", "started": "2026-10-17"}).json()["patients"][0]
    assert other.post(f"/api/care/episodes/{p['episodes'][0]['id']}/import-local").status_code == 403
    target = workspace["patients"][0]["episodes"][0]["id"]
    assert client.post(f"/api/care/episodes/{target}/import-local").status_code == 200
    assert client.get("/api/reports").json()[0]["id"] == report["id"]


def test_password_hash_session_expiry_and_origin_checks(client):
    token = client.cookies.get("aftercare_session")
    with store.connect() as db:
        stored = db.execute("SELECT password FROM users").fetchone()[0]
        assert "fictional-password-123" not in stored
        assert db.execute("SELECT token FROM sessions").fetchone()[0] == hashlib.sha256(token.encode()).hexdigest()
        db.execute("UPDATE sessions SET expires=?", (time.time() - 1,))
    assert client.get("/api/reports").status_code == 401
    assert client.post("/api/auth/login", json={"username": "test-owner", "password": "fictional-password-123"}).status_code == 200
    assert client.post("/api/auth/logout", headers={"Origin": "https://evil.example"}).status_code == 403
    no_origin = other_client()
    no_origin.headers.pop("Origin")
    assert no_origin.post("/api/auth/login", json={"username": "test-owner", "password": "fictional-password-123"}).status_code == 403
    assert client.get("/api/reports", headers={"Host": "evil.example"}).status_code == 403


def test_login_throttle_and_cookie_flags(client):
    other = other_client()
    body = {"username": "missing", "password": "wrong-password-123"}
    for _ in range(10):
        assert other.post("/api/auth/login", json=body).status_code == 401
    assert other.post("/api/auth/login", json=body).status_code == 429
    response = client.post("/api/auth/login", json={"username": "TEST-OWNER", "password": "fictional-password-123"})
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/api" in cookie
