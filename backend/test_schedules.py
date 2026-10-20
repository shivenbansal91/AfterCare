from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from . import store
from .main import app
from .schedules import occurrence_times
from .test_tracking import reviewed_report


@pytest.fixture
def doctor(client):
    reviewer = TestClient(app, base_url="http://127.0.0.1:8000", headers={"Origin": "http://127.0.0.1:5173"})
    user = reviewer.post("/api/auth/register", json={"username": "fictional-clinician", "password": "fictional-doctor-password"}).json()
    with store.connect() as db:
        db.execute("INSERT INTO clinicians VALUES (?,?,?,?,?,?,1,1)", (user["id"], "Demo clinician", "DEMO ONLY", "Test fixture", "Synthetic verification", "2099-01-01T00:00:00+00:00"))
    return reviewer, user["id"]


def proposal(clinician_id, **changes):
    today = datetime.now(timezone.utc).date()
    return {"group": "Medication 1", "clinician_id": clinician_id, "dose": "1 capsule", "times": ["00:00", "23:59"],
            "start": today.isoformat(), "end": (today + timedelta(days=4)).isoformat(), "timezone": "UTC", "consent": True, **changes}


def requested(client, reviewed_report, doctor):
    reviewer, identity = doctor
    url = f"/api/reports/{reviewed_report['id']}/schedules"
    result = client.post(url, json=proposal(identity))
    assert result.status_code == 201, result.text
    return url, result.json()[0]


def approve(doctor, schedule, **changes):
    return doctor[0].post(f"/api/clinical/schedules/{schedule['id']}/decision", json={
        "decision": "approved", "note": "Synthetic fixture reviewed against original source.",
        "fingerprint": schedule["fingerprint"], "attestation": True, **changes})


def test_owner_cannot_self_approve_and_clinician_needs_specific_consent(client, reviewed_report, doctor):
    reviewer, identity = doctor
    report_id = reviewed_report["id"]
    assert reviewer.get(f"/api/reports/{report_id}/file").status_code == 404
    url, schedule = requested(client, reviewed_report, doctor)
    assert reviewer.get(f"/api/reports/{report_id}/file").status_code == 200
    assert client.post(f"/api/clinical/schedules/{schedule['id']}/decision", json={"decision": "approved", "note": "I am the patient owner", "fingerprint": schedule["fingerprint"], "attestation": True}).status_code == 404
    assert reviewer.patch(f"/api/reports/{report_id}/fields/{reviewed_report['fields'][0]['id']}", json={"status": "confirmed", "value": "tamper"}).status_code == 404
    assert approve(doctor, schedule).status_code == 200
    assert client.get(url).json()[0]["status"] == "approved"
    assert client.post(url, json=proposal(identity)).status_code == 409
    assert client.post(url + f"/{schedule['id']}/stop").status_code == 200
    assert reviewer.get(f"/api/reports/{report_id}/file").status_code == 404
    assert client.get(url).json()[0]["doses"] == []


def test_correction_and_archive_never_revive_old_approval(client, reviewed_report, doctor):
    url, schedule = requested(client, reviewed_report, doctor)
    assert approve(doctor, schedule).status_code == 200
    field = reviewed_report["fields"][0]
    endpoint = f"/api/reports/{reviewed_report['id']}"
    for value in ["Corrected detail", field["value"]]:
        client.patch(endpoint + f"/fields/{field['id']}", json={"status": "confirmed", "value": value})
    client.post(endpoint + "/plan")
    assert client.get(url).json()[0]["status"] == "suspended"
    assert client.post(url, json=proposal(doctor[1])).status_code == 201
    new = client.get(url).json()[0]
    assert approve(doctor, new).status_code == 200
    client.post(endpoint + "/archive")
    client.post(endpoint + "/restore")
    assert all(s["status"] == "suspended" for s in client.get(url).json())


def test_stale_rejected_and_unreviewed_schedules_cannot_activate(client, reviewed_report, doctor):
    url, schedule = requested(client, reviewed_report, doctor)
    assert approve(doctor, schedule, fingerprint="stale").status_code == 409
    assert approve(doctor, schedule, decision="rejected").status_code == 200
    assert approve(doctor, schedule).status_code == 404
    result = client.post(url, json=proposal(doctor[1]))
    assert result.status_code == 201
    field = reviewed_report["fields"][0]
    client.patch(f"/api/reports/{reviewed_report['id']}/fields/{field['id']}", json={"status": "clarify", "value": field["value"]})
    assert approve(doctor, result.json()[0]).status_code == 404


@pytest.mark.parametrize("changes", [{"times": ["25:00"]}, {"times": ["08:00", "08:00"]}, {"timezone": "Invalid/Zone"},
                                      {"end": "2000-01-01"}, {"consent": False}, {"dose": " "}, {"times": []}])
def test_invalid_schedule_is_rejected(client, reviewed_report, doctor, changes):
    response = client.post(f"/api/reports/{reviewed_report['id']}/schedules", json=proposal(doctor[1], **changes))
    assert response.status_code == 422


def test_expired_credentials_and_demo_limits(client, reviewed_report, doctor):
    url, schedule = requested(client, reviewed_report, doctor)
    assert approve(doctor, schedule).status_code == 200
    with store.connect() as db:
        db.execute("UPDATE clinicians SET valid_until='2000-01-01T00:00:00+00:00'")
    assert client.get(url).json()[0]["status"] == "suspended"
    assert doctor[0].get(f"/api/reports/{reviewed_report['id']}/file").status_code == 404
    with store.connect() as db:
        import json
        db.execute("UPDATE clinicians SET valid_until='2099-01-01T00:00:00+00:00'")
        report = dict(reviewed_report, sample=False)
        db.execute("UPDATE reports SET payload=? WHERE id=?", (json.dumps(report), report["id"]))
    assert client.post(url, json=proposal(doctor[1])).status_code == 422


def test_scheduled_dose_idempotency_undo_snooze_and_permission(client, reviewed_report, doctor):
    url, schedule = requested(client, reviewed_report, doctor)
    assert approve(doctor, schedule).status_code == 200
    doses = client.get(url).json()[0]["doses"]
    action_url = url + f"/{schedule['id']}/dose"
    body = {"due_at": doses[0]["due_at"], "action": "taken", "note": "Fixture"}
    assert doctor[0].post(action_url, json=body).status_code == 404
    assert client.post(action_url, json={**body, "due_at": doses[1]["due_at"]}).status_code == 422
    assert client.post(action_url, json={**body, "due_at": "2026-10-18T01:23:00+00:00"}).status_code == 422
    for _ in range(2):
        response = client.post(action_url, json=body)
        assert response.status_code == 200, response.text
    assert response.json()[0]["doses"][0]["status"] == "taken"
    assert client.post(action_url, json={**body, "action": "skipped"}).status_code == 409
    assert client.post(action_url, json={**body, "action": "undo"}).json()[0]["doses"][0]["status"] == "pending"
    assert client.post(action_url, json={**body, "action": "snooze"}).json()[0]["doses"][0]["snoozed_until"]
    client.post(url + f"/{schedule['id']}/stop")
    assert client.post(action_url, json=body).status_code == 409
    with store.connect() as db:
        assert db.execute("SELECT snapshot FROM scheduled_doses").fetchone()[0]
        assert db.execute("SELECT COUNT(*) FROM care_audit WHERE action='dose_taken'").fetchone()[0] == 1


def test_dst_and_local_date_boundaries():
    from datetime import date
    payload = {"start": "2026-01-01", "end": "2026-12-31", "timezone": "America/New_York", "times": ["01:30", "02:30"]}
    assert len(occurrence_times(payload, date(2026, 3, 8))) == 1
    assert len(occurrence_times(payload, date(2026, 11, 1))) == 2
    assert occurrence_times({**payload, "timezone": "Asia/Kolkata", "times": ["00:10"]}, date(2026, 10, 18)) == ["2026-10-17T18:40:00+00:00"]
    assert occurrence_times(payload, date(2027, 1, 1)) == []


def test_clinician_withdrawal_and_backup_restore_disable_prior_approvals(client, reviewed_report, doctor, tmp_path):
    import sqlite3
    from . import backup, vault
    url, schedule = requested(client, reviewed_report, doctor)
    assert approve(doctor, schedule).status_code == 200
    path = tmp_path / "clinical.acb"
    backup.create_backup(store.DATA, path, "fictional-clinical-backup-password")
    restored = tmp_path / "clinical-restored"
    backup.restore_backup(path, restored, "fictional-clinical-backup-password")
    with sqlite3.connect(":memory:") as db:
        db.deserialize(vault.read(restored / "aftercare.db"))
        assert db.execute("SELECT status,consent FROM schedules").fetchone() == ("suspended", 0)
        assert db.execute("SELECT active FROM clinicians").fetchone()[0] == 0
    assert doctor[0].post(f"/api/clinical/schedules/{schedule['id']}/revoke", json={"reason": "Synthetic approval withdrawn after recheck."}).status_code == 200
    assert client.get(url).json()[0]["status"] == "suspended"
    assert doctor[0].get(f"/api/reports/{reviewed_report['id']}/file").status_code == 404
