from datetime import datetime, timedelta, timezone
from uuid import uuid4

from . import store
from .test_personal import active
from .test_sharing import caregiver, invite


def queued(schedule, **changes):
    return {"action": "taken", "due_at": schedule["doses"][0]["due_at"], "offline": {
        "request_id": str(uuid4()), "fingerprint": schedule["fingerprint"], "expected_recorded_at": None,
        "recorded_at": datetime.now(timezone.utc).isoformat(), **changes}}


def test_snapshot_keeps_own_evidence_and_excludes_shared_records(client, caregiver):
    report, schedule = active(client)
    response = client.get("/api/mobile/snapshot")
    assert response.status_code == 200, response.text
    snapshot = response.json()
    assert snapshot["reports"][0]["fields"] == report["fields"]
    assert snapshot["schedules"][report["id"]][0]["fingerprint"] == schedule["fingerprint"]
    assert len(snapshot["schedules"][report["id"]][0]["offline_doses"]) == 10
    _, invitation = invite(client, "recorder")
    caregiver.post(f"/api/care/invitations/{invitation}/respond", json={"action": "accept"})
    assert any(value["id"] == report["id"] for value in caregiver.get("/api/reports").json())
    shared_snapshot = caregiver.get("/api/mobile/snapshot").json()
    assert shared_snapshot["reports"] == []
    assert all(patient["access_role"] == "owner" for patient in shared_snapshot["workspace"]["patients"])
    url = f"/api/reports/{report['id']}/schedules/{schedule['id']}/dose"
    assert caregiver.post(url, json=queued(schedule)).status_code == 403


def test_offline_retry_is_idempotent_and_cannot_reuse_request_for_new_action(client):
    report, schedule = active(client)
    body = queued(schedule)
    url = f"/api/reports/{report['id']}/schedules/{schedule['id']}/dose"
    assert client.post(url, json=body).status_code == 200
    assert client.post(url, json=body).status_code == 200
    assert client.post(url, json={**body, "action": "skipped"}).status_code == 409
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM mobile_dose_receipts").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM care_audit WHERE action='dose_taken'").fetchone()[0] == 1


def test_offline_dose_cannot_overwrite_another_device(client):
    report, schedule = active(client)
    body = queued(schedule)
    url = f"/api/reports/{report['id']}/schedules/{schedule['id']}/dose"
    assert client.post(url, json={"due_at": body["due_at"], "action": "skipped"}).status_code == 200
    result = client.post(url, json=body)
    assert result.status_code == 409
    assert "another device" in result.json()["detail"]
    assert client.get(f"/api/reports/{report['id']}/schedules").json()[0]["doses"][0]["status"] == "skipped"


def test_offline_chain_supports_undo_without_overwriting_later_edits(client):
    report, schedule = active(client)
    url = f"/api/reports/{report['id']}/schedules/{schedule['id']}/dose"
    taken = queued(schedule)
    assert client.post(url, json=taken).status_code == 200
    undo = queued(schedule, after_request_id=taken["offline"]["request_id"])
    undo["action"] = "undo"
    assert client.post(url, json=undo).status_code == 200
    assert client.post(url, json=undo).status_code == 200
    assert client.post(url, json={"due_at": taken["due_at"], "action": "skipped"}).status_code == 200
    later = queued(schedule, after_request_id=undo["offline"]["request_id"])
    assert client.post(url, json=later).status_code == 409


def test_changed_or_stopped_plan_rejects_delayed_recording(client):
    report, schedule = active(client)
    url = f"/api/reports/{report['id']}/schedules/{schedule['id']}/dose"
    assert client.post(url, json=queued(schedule, fingerprint="0" * 64)).status_code == 409
    assert client.post(f"/api/reports/{report['id']}/schedules/{schedule['id']}/stop").status_code == 200
    assert client.post(url, json=queued(schedule)).status_code == 409
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM scheduled_doses").fetchone()[0] == 0


def test_delayed_offline_snooze_does_not_restart_ten_minutes_on_sync(client):
    report, schedule = active(client)
    body = queued(schedule, recorded_at=schedule["doses"][0]["due_at"])
    body["action"] = "snooze"
    response = client.post(f"/api/reports/{report['id']}/schedules/{schedule['id']}/dose", json=body)
    assert response.status_code == 200
    expected = datetime.fromisoformat(body["offline"]["recorded_at"]) + timedelta(minutes=10)
    assert datetime.fromisoformat(response.json()[0]["doses"][0]["snoozed_until"]) == expected
