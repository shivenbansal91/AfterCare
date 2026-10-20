import base64
import secrets

import pytest

from . import config, store, vault
from .test_schedules import approve, doctor, requested
from .test_tracking import reviewed_report
from .test_sharing import caregiver, invite


def test_permanent_delete_requires_owner_archive_exact_name_and_password(client, reviewed_report, doctor, caregiver):
    url, schedule = requested(client, reviewed_report, doctor)
    approve(doctor, schedule)
    prefix = f"/api/reports/{reviewed_report['id']}"
    path = store.DATA / reviewed_report["file"]
    original = path.read_bytes()
    body = {"current_password": "fictional-password-123", "name": reviewed_report["name"]}
    assert client.request("DELETE", prefix, json=body).status_code == 409
    _, invitation = invite(client, "recorder")
    caregiver.post(f"/api/care/invitations/{invitation}/respond", json={"action": "accept"})
    client.post(prefix + "/archive")
    assert caregiver.request("DELETE", prefix, json=body).status_code == 403
    assert client.request("DELETE", prefix, json={**body, "current_password": "wrong"}).status_code == 403
    assert client.request("DELETE", prefix, json={**body, "name": "wrong"}).status_code == 422
    assert path.read_bytes() == original
    assert client.request("DELETE", prefix, json=body).status_code == 200
    assert not path.exists()
    assert client.post(prefix + "/restore").status_code == 404
    assert doctor[0].get(prefix + "/file").status_code == 404
    with store.connect() as db:
        for table in ("reports", "report_access", "report_archives", "reviews", "schedules", "scheduled_doses"):
            assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        assert db.execute("SELECT action FROM care_audit ORDER BY id DESC").fetchone()[0] == "report_permanently_deleted"


def test_interrupted_deletion_recovers_from_database_state(client):
    report = client.post("/api/reports/sample").json()
    path = store.DATA / report["file"]
    original = path.read_bytes()
    tomb = path.with_name(".delete-" + path.name)
    path.replace(tomb)
    vault.initialize(store.DATA)
    assert vault.read(path) == original
    assert not tomb.exists()
    orphan = store.DATA / ".delete-orphan.pdf"
    orphan.write_bytes(b"Already deleted")
    vault.initialize(store.DATA)
    assert not orphan.exists()


def test_remote_configuration_fails_closed_and_keeps_local_ollama(monkeypatch):
    monkeypatch.setenv("AFTERCARE_PUBLIC_ORIGIN", "https://care.example.org")
    monkeypatch.delenv("AFTERCARE_VAULT_KEY", raising=False)
    monkeypatch.delenv("AFTERCARE_SECURE_COOKIE", raising=False)
    with pytest.raises(ValueError, match="secure cookies"):
        config.validate()
    monkeypatch.setenv("AFTERCARE_SECURE_COOKIE", "1")
    monkeypatch.setenv("AFTERCARE_VAULT_KEY", base64.b64encode(secrets.token_bytes(32)).decode())
    config.validate()
    assert "care.example.org" in config.allowed_hosts()
    assert "https://care.example.org" in config.allowed_origins()
    monkeypatch.setenv("OLLAMA_URL", "https://external-ai.example.org")
    with pytest.raises(ValueError, match="locally"):
        config.validate()
