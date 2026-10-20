import hashlib
from concurrent.futures import ThreadPoolExecutor

from . import store
from .test_accounts import other_client

PASSWORD = "fictional-password-123"
NEW_PASSWORD = "replacement-password-456"


def recovery_code(client):
    response = client.post("/api/auth/recovery-code", json={"current_password": PASSWORD})
    assert response.status_code == 200
    return response.json()["recovery_code"]


def recover(client, code, username="test-owner"):
    return client.post("/api/auth/recover", json={"username": username, "recovery_code": code, "new_password": NEW_PASSWORD})


def test_recovery_code_is_hashed_and_only_current_password_can_rotate_it(client):
    assert client.get("/api/auth/security").json() == {"recovery_configured": False}
    code = recovery_code(client)
    assert client.get("/api/auth/security").json() == {"recovery_configured": True}
    with store.connect() as db:
        row = db.execute("SELECT * FROM recovery_codes").fetchone()
        assert row["code_hash"] == hashlib.sha256(code.encode()).hexdigest()
        assert code not in str(dict(row))
    assert client.post("/api/auth/recovery-code", json={"current_password": "wrong"}).status_code == 401
    assert recover(other_client(), code).status_code == 200


def test_recovery_consumes_code_revokes_sessions_and_keeps_records(client):
    report = client.post("/api/reports/sample").json()
    cookie = client.cookies.get("aftercare_session")
    code = recovery_code(client)
    visitor = other_client()
    assert recover(visitor, code).status_code == 200
    assert visitor.cookies.get("aftercare_session") is None
    assert recover(visitor, code).status_code == 401
    client.cookies.set("aftercare_session", cookie)
    assert client.get("/api/reports").status_code == 401
    assert visitor.post("/api/auth/login", json={"username": "test-owner", "password": PASSWORD}).status_code == 401
    assert visitor.post("/api/auth/login", json={"username": "test-owner", "password": NEW_PASSWORD}).status_code == 200
    assert visitor.get(f"/api/reports/{report['id']}").status_code == 200
    assert visitor.get("/api/auth/security").json()["recovery_configured"] is False


def test_rotated_and_cross_account_codes_cannot_reset_passwords(client):
    first = recovery_code(client)
    current = recovery_code(client)
    outsider = other_client()
    outsider.post("/api/auth/register", json={"username": "outsider", "password": PASSWORD})
    assert recover(outsider, current, "outsider").status_code == 401
    assert recover(outsider, first).status_code == 401
    assert recover(outsider, current).status_code == 200
    assert outsider.get("/api/auth/session").json()["username"] == "outsider"


def test_password_change_rechecks_proof_revokes_old_sessions_and_recovery_code(client):
    second = other_client()
    second.post("/api/auth/login", json={"username": "test-owner", "password": PASSWORD})
    code = recovery_code(client)
    assert client.post("/api/auth/password", json={"current_password": "wrong", "new_password": NEW_PASSWORD}).status_code == 401
    assert second.get("/api/auth/session").status_code == 200
    assert client.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": PASSWORD}).status_code == 422
    assert client.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": NEW_PASSWORD}).status_code == 200
    assert client.get("/api/auth/session").status_code == 200
    assert second.get("/api/auth/session").status_code == 401
    assert recover(other_client(), code).status_code == 401


def test_recovery_is_single_use_under_concurrent_requests(client):
    code = recovery_code(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: recover(other_client(), code).status_code, range(2)))
    assert sorted(results) == [200, 401]


def test_recovery_is_throttled_and_needs_same_origin(client):
    visitor = other_client()
    for _ in range(10):
        assert recover(visitor, "wrong").status_code == 401
    assert recover(visitor, "wrong").status_code == 429
    visitor.headers.pop("origin")
    assert recover(visitor, "wrong").status_code == 403
