import sqlite3
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from . import store
from .test_accounts import other_client


@pytest.fixture
def caregiver(client):
    helper = other_client()
    helper.post("/api/auth/register", json={"username": "care-helper", "password": "caregiver-password-123"})
    return helper


def invite(owner, role="viewer"):
    patient = owner.get("/api/care").json()["patients"][0]
    response = owner.post(f"/api/care/patients/{patient['id']}/invitations", json={"username": "care-helper", "role": role})
    assert response.status_code == 201
    return patient, response.json()["patients"][0]["sharing"][0]["id"]


def reviewed(owner):
    report = owner.post("/api/reports/sample").json()
    for field in report["fields"]:
        owner.patch(f"/api/reports/{report['id']}/fields/{field['id']}", json={"status": "confirmed", "value": field["value"]})
    owner.post(f"/api/reports/{report['id']}/plan")
    return report


def event(**changes):
    return {"request_id": str(uuid4()), "group": "Medication 1", "status": "taken", **changes}


@pytest.mark.parametrize("role", ["viewer", "recorder"])
def test_acceptance_scopes_all_read_surfaces_and_cannot_escalate(client, caregiver, role):
    report = reviewed(client)
    patient, invitation = invite(client, role)
    prefix = f"/api/reports/{report['id']}"
    assert caregiver.get("/api/reports").json() == []
    assert caregiver.get(prefix + "/file").status_code == 404
    assert len(caregiver.get("/api/care").json()["invitations"]) == 1
    accepted = caregiver.post(f"/api/care/invitations/{invitation}/respond", json={"action": "accept"})
    assert accepted.status_code == 200
    assert accepted.json()["patients"][0]["access_role"] == role
    for suffix in ["", "/file", "/pages/0", "/plan", "/history", "/activity"]:
        assert caregiver.get(prefix + suffix).status_code == 200
    field = report["fields"][0]
    assert caregiver.patch(f"{prefix}/fields/{field['id']}", json={"status": "confirmed", "value": "tampered"}).status_code == 403
    assert caregiver.post(prefix + "/plan").status_code == 403
    assert caregiver.post(prefix + "/reread").status_code == 403
    assert caregiver.post(f"/api/reports/sample?episode_id={report['episode_id']}").status_code == 404
    assert caregiver.post(f"/api/care/patients/{patient['id']}/episodes", json={"title": "Tampered", "started": "2026-10-17"}).status_code == 404
    assert caregiver.post(f"/api/care/patients/{patient['id']}/invitations", json={"username": "test-owner", "role": "recorder"}).status_code == 404
    assert caregiver.get(f"/api/care/patients/{patient['id']}/access-history").status_code == 404
    assert caregiver.post(f"/api/care/patients/{patient['id']}/contacts", json={"name": "Wrong", "role": "Other", "phone": "12345"}).status_code == 404
    second = client.post("/api/care/patients", json={"name": "Unshared patient"}).json()["patients"][1]
    second = client.post(f"/api/care/patients/{second['id']}/episodes", json={"title": "Unshared", "started": "2026-10-17"}).json()["patients"][1]
    hidden = client.post(f"/api/reports/sample?episode_id={second['episodes'][0]['id']}").json()
    assert caregiver.get(f"/api/reports/{hidden['id']}/file").status_code == 404
    assert len(caregiver.get("/api/care").json()["patients"]) == 1
    future = client.post(f"/api/reports/sample?episode_id={report['episode_id']}").json()
    assert caregiver.get(f"/api/reports/{future['id']}").status_code == 200


def test_viewer_cannot_write_activity_or_undo_owner_records(client, caregiver):
    report = reviewed(client)
    _, invitation = invite(client)
    caregiver.post(f"/api/care/invitations/{invitation}/respond", json={"action": "accept"})
    prefix = f"/api/reports/{report['id']}"
    logged = client.post(prefix + "/medications/log", json=event()).json()["medications"][0]
    assert caregiver.post(prefix + "/medications/log", json=event()).status_code == 403
    assert caregiver.post(f"{prefix}/medications/log/{logged['id']}/undo").status_code == 403
    field = next(f for f in report["fields"] if f["group"] == "Visits")
    assert caregiver.put(f"{prefix}/visits/{field['id']}", json={"status": "completed"}).status_code == 403


def test_recorder_attribution_own_undo_audit_and_revocation(client, caregiver):
    report = reviewed(client)
    patient, invitation = invite(client, "recorder")
    caregiver.post(f"/api/care/invitations/{invitation}/respond", json={"action": "accept"})
    prefix = f"/api/reports/{report['id']}"
    body = event(note="Fictional care event")
    for _ in range(2):
        result = caregiver.post(prefix + "/medications/log", json=body)
        assert result.status_code == 201
        assert len(result.json()["medications"]) == 1
    helper_entry = result.json()["medications"][0]
    assert helper_entry["actor_name"] == "care-helper"
    assert client.post(prefix + "/medications/log", json=body).status_code == 409
    owner_entry = client.post(prefix + "/medications/log", json=event()).json()["medications"][0]
    assert caregiver.post(f"{prefix}/medications/log/{owner_entry['id']}/undo").status_code == 403
    assert caregiver.post(f"{prefix}/medications/log/{helper_entry['id']}/undo").status_code == 200
    assert caregiver.post(f"{prefix}/medications/log/{helper_entry['id']}/undo").status_code == 200
    visit = next(f for f in report["fields"] if f["group"] == "Visits")
    updated = caregiver.put(f"{prefix}/visits/{visit['id']}", json={"status": "booked", "planned_date": "2026-11-02", "note": "Fictional booking"})
    assert updated.json()["visits"][0]["actor_name"] == "care-helper"
    assert client.post(f"/api/care/patients/{patient['id']}/invitations/{invitation}/revoke").status_code == 200
    for suffix in ["", "/file", "/pages/0", "/plan", "/history", "/activity"]:
        assert caregiver.get(prefix + suffix).status_code == 404
    assert caregiver.post(prefix + "/medications/log", json=event()).status_code == 404
    assert caregiver.put(f"{prefix}/visits/{visit['id']}", json={"status": "completed"}).status_code == 404
    assert caregiver.get("/api/reports").json() == []
    assert caregiver.get("/api/care").json()["patients"] == []
    assert client.get(prefix + "/activity").json()["visits"][0]["note"] == "Fictional booking"
    audit = client.get(f"/api/care/patients/{patient['id']}/access-history").json()
    assert {e["action"] for e in audit} >= {"invited", "accepted", "medication_recorded", "medication_undone", "visit_updated", "revoked"}
    assert sum(e["action"] == "medication_undone" for e in audit) == 1
    assert any(e["actor_name"] == "care-helper" and e["action"] == "visit_updated" for e in audit)
    assert next(e for e in audit if e["action"] == "revoked")["recipient_name"] == "care-helper"


def test_recorder_still_requires_reviewed_plan(client, caregiver):
    report = client.post("/api/reports/sample").json()
    patient, invitation = invite(client, "recorder")
    caregiver.post(f"/api/care/invitations/{invitation}/respond", json={"action": "accept"})
    assert caregiver.post(f"/api/reports/{report['id']}/medications/log", json=event()).status_code == 409


def test_invitation_decline_expiry_and_recipient_cannot_accept_for_others(client, caregiver):
    patient, invitation = invite(client)
    prefix = f"/api/care/patients/{patient['id']}"
    assert client.post(f"/api/care/invitations/{invitation}/respond", json={"action": "accept"}).status_code == 404
    assert caregiver.post(f"{prefix}/invitations/{invitation}/revoke").status_code == 404
    assert client.post(prefix + "/invitations", json={"username": "care-helper", "role": "recorder"}).status_code == 409
    assert caregiver.post(f"/api/care/invitations/{invitation}/respond", json={"action": "decline"}).status_code == 200
    assert caregiver.post(f"/api/care/invitations/{invitation}/respond", json={"action": "accept"}).status_code == 409
    _, invitation = invite(client)
    with store.connect() as db:
        db.execute("UPDATE caregiver_access SET expires_at=? WHERE id=?", ((datetime.now(timezone.utc) - timedelta(days=1)).isoformat(), invitation))
    assert caregiver.get("/api/care").json()["invitations"] == []
    assert caregiver.post(f"/api/care/invitations/{invitation}/respond", json={"action": "accept"}).status_code == 409
    _, fresh = invite(client, "recorder")
    assert fresh != invitation
    assert caregiver.post(f"/api/care/invitations/{fresh}/respond", json={"action": "accept"}).status_code == 200


def test_revoked_pending_invitation_cannot_be_reaccepted(client, caregiver):
    patient, invitation = invite(client)
    client.post(f"/api/care/patients/{patient['id']}/invitations/{invitation}/revoke")
    assert caregiver.post(f"/api/care/invitations/{invitation}/respond", json={"action": "accept"}).status_code == 409
    assert caregiver.get("/api/care").json()["patients"] == []


def test_existing_tracking_tables_migrate_without_losing_legacy_records(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA", tmp_path)
    with sqlite3.connect(tmp_path / "aftercare.db") as db:
        db.executescript("""CREATE TABLE medication_entries (id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL,
            report_id TEXT NOT NULL, medication_group TEXT NOT NULL, status TEXT NOT NULL, occurred_at TEXT NOT NULL,
            note TEXT NOT NULL, snapshot TEXT NOT NULL, created_at TEXT NOT NULL, voided_at TEXT);
            INSERT INTO medication_entries VALUES ('legacy','request','report','Medication 1','taken','2026-10-17','note','{}','2026-10-17',NULL);
            CREATE TABLE visits (report_id TEXT,field_id TEXT,status TEXT,planned_date TEXT,note TEXT,source_value TEXT,updated_at TEXT,PRIMARY KEY(report_id,field_id));""")
    for _ in range(2):
        with store.connect() as db:
            row = db.execute("SELECT * FROM medication_entries WHERE id='legacy'").fetchone()
            assert row["note"] == "note" and row["actor_id"] is None and row["voided_by"] is None


def test_revocation_between_read_and_write_blocks_record(client, caregiver, monkeypatch):
    report = reviewed(client)
    _, invitation = invite(client, "recorder")
    caregiver.post(f"/api/care/invitations/{invitation}/respond", json={"action": "accept"})
    original = store.get
    revoked = False

    def revoke_after_read(report_id, db=None):
        nonlocal revoked
        result = original(report_id, db)
        if db is None and not revoked:
            revoked = True
            with store.connect() as connection:
                connection.execute("UPDATE caregiver_access SET status='revoked' WHERE id=?", (invitation,))
        return result

    monkeypatch.setattr(store, "get", revoke_after_read)
    assert caregiver.post(f"/api/reports/{report['id']}/medications/log", json=event()).status_code == 404
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM medication_entries").fetchone()[0] == 0
