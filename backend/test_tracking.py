import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from . import store


@pytest.fixture
def reviewed_report(client):
    report = client.post("/api/reports/sample").json()
    for field in report["fields"]:
        client.patch(f"/api/reports/{report['id']}/fields/{field['id']}", json={"value": field["value"], "status": "confirmed"})
    return client.post(f"/api/reports/{report['id']}/plan").json()


def entry(**changes):
    return {"request_id": str(uuid4()), "group": "Medication 1", "status": "taken", **changes}


def test_unreviewed_plan_cannot_create_activity(client):
    report = client.post("/api/reports/sample").json()
    prefix = f"/api/reports/{report['id']}"
    assert client.post(f"{prefix}/medications/log", json=entry()).status_code == 409
    field = next(f for f in report["fields"] if f["group"] == "Visits")
    assert client.put(f"{prefix}/visits/{field['id']}", json={"status": "completed"}).status_code == 409


def test_medication_logs_are_idempotent_and_undoable(client, reviewed_report):
    prefix = f"/api/reports/{reviewed_report['id']}"
    body = entry(note="Fictional test")
    for _ in range(2):
        result = client.post(f"{prefix}/medications/log", json=body)
        assert result.status_code == 201
        assert len(result.json()["medications"]) == 1
    logged = result.json()["medications"][0]
    assert logged["snapshot"]["Name"] == "Amoxicillin"
    assert client.post(f"{prefix}/medications/log", json={**body, "status": "skipped"}).status_code == 409
    assert client.post(f"{prefix}/medications/log/{logged['id']}/undo").json()["medications"] == []
    with store.connect() as db:
        assert db.execute("SELECT voided_at FROM medication_entries WHERE id=?", (logged["id"],)).fetchone()[0]


def test_clarification_and_future_time_block_logging(client, reviewed_report):
    prefix = f"/api/reports/{reviewed_report['id']}"
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    assert client.post(f"{prefix}/medications/log", json=entry(occurred_at=future)).status_code == 422
    assert client.post(f"{prefix}/medications/log", json=entry(occurred_at="2026-10-17T12:00:00")).status_code == 422
    field = next(f for f in reviewed_report["fields"] if f["group"] == "Medication 1" and f["label"] == "Dose")
    client.patch(f"{prefix}/fields/{field['id']}", json={"value": field["value"], "status": "clarify"})
    client.post(f"{prefix}/plan")
    assert client.post(f"{prefix}/medications/log", json=entry()).status_code == 409


def test_log_snapshot_survives_source_correction(client, reviewed_report):
    prefix = f"/api/reports/{reviewed_report['id']}"
    client.post(f"{prefix}/medications/log", json=entry())
    field = next(f for f in reviewed_report["fields"] if f["group"] == "Medication 1" and f["label"] == "Name")
    client.patch(f"{prefix}/fields/{field['id']}", json={"value": "Corrected medicine", "status": "confirmed"})
    assert client.post(f"{prefix}/medications/log", json=entry()).status_code == 409
    assert client.get(f"{prefix}/activity").json()["medications"][0]["snapshot"]["Name"] == "Amoxicillin"


def test_visit_booking_and_completion(client, reviewed_report):
    prefix = f"/api/reports/{reviewed_report['id']}"
    field = next(f for f in reviewed_report["fields"] if f["group"] == "Visits")
    url = f"{prefix}/visits/{field['id']}"
    assert client.put(url, json={"status": "booked"}).status_code == 422
    result = client.put(url, json={"status": "booked", "planned_date": "2026-11-02", "note": "Morning appointment"})
    assert result.status_code == 200
    visit = result.json()["visits"][0]
    assert visit["source_value"] == field["value"]
    assert visit["planned_date"] == "2026-11-02"
    assert client.put(url, json={"status": "completed"}).json()["visits"][0]["status"] == "completed"
    assert client.put(f"{prefix}/visits/missing", json={"status": "completed"}).status_code == 404


def test_activity_cannot_cross_reports(client, reviewed_report):
    first = f"/api/reports/{reviewed_report['id']}"
    logged = client.post(f"{first}/medications/log", json=entry()).json()["medications"][0]
    other = client.post("/api/reports/sample").json()
    second = f"/api/reports/{other['id']}"
    assert client.get(f"{second}/activity").json() == {"medications": [], "visits": []}
    assert client.post(f"{second}/medications/log/{logged['id']}/undo").status_code == 404


def test_conflicting_medication_fields_cannot_be_logged(client, reviewed_report):
    dose = next(f for f in reviewed_report["fields"] if f["group"] == "Medication 1" and f["label"] == "Dose")
    reviewed_report["fields"].append({**dose, "id": uuid4().hex, "value": "2 capsules"})
    with store.connect() as db:
        db.execute("UPDATE reports SET payload=? WHERE id=?", (json.dumps(reviewed_report), reviewed_report["id"]))
    response = client.post(f"/api/reports/{reviewed_report['id']}/medications/log", json=entry())
    assert response.status_code == 409
    assert "repeated fields" in response.json()["detail"]
