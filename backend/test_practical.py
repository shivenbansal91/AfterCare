import io
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zipfile import ZipFile

import pytest

from . import backup, store, vault
from .test_accounts import other_client
from .test_sharing import caregiver, invite


def manual(client, **changes):
    body = {"request_id": str(uuid4()), "name": "Ibuprofen", "strength": "400 mg", "dose": "1 tablet",
            "frequency": "Once daily", "duration": "5 days", "confirmed": True, **changes}
    response = client.post("/api/medicines/manual", json=body)
    assert response.status_code == 201, response.text
    return response.json(), body


def reminder(report, **changes):
    today = datetime.now(timezone.utc).date()
    return {"group": "Medication 1", "dose": "1 tablet", "times": ["13:00"], "start": today.isoformat(),
            "end": (today + timedelta(days=4)).isoformat(), "timezone": "Asia/Kolkata", "confirmed": True,
            "revision": report["revision"], **changes}


def test_manual_entry_needs_no_document_and_retries_do_not_duplicate_it(client):
    report, body = manual(client)
    assert report["kind"] == "manual" and report["file"] is None and report["pages"] == []
    assert report["plan_saved"] and all(field["origin"] == "manual" and field["source"] is None for field in report["fields"])
    assert client.get(f"/api/reports/{report['id']}/file").status_code == 404
    assert client.get(f"/api/reports/{report['id']}/pages/0").status_code == 404
    assert client.get(f"/api/reports/{report['id']}/schedules").json() == []
    assert client.post("/api/medicines/manual", json=body).json() == report
    assert len(client.get("/api/reports").json()) == 1
    assert client.post("/api/medicines/manual", json={**body, "dose":"2 tablets"}).status_code == 409
    assert client.post("/api/medicines/manual", json={**body, "request_id":str(uuid4()), "name":" "}).status_code == 422


def test_manual_medicine_keeps_owner_and_caretaker_permissions(client, caregiver):
    report, body = manual(client)
    _, grant = invite(client, "viewer")
    caregiver.post(f"/api/care/invitations/{grant}/respond", json={"action":"accept"})
    assert caregiver.get(f"/api/reports/{report['id']}").status_code == 200
    assert caregiver.post(f"/api/medicines/manual?episode_id={report['episode_id']}", json={**body,"request_id":str(uuid4())}).status_code == 404
    assert caregiver.post(f"/api/reports/{report['id']}/reminders", json=reminder(report)).status_code == 403
    visitor = other_client()
    visitor.post("/api/auth/register", json={"username":"manual-outsider","password":"fictional-outsider-password"})
    assert visitor.get(f"/api/reports/{report['id']}/overview").status_code == 404
    assert visitor.post("/api/medicines/manual", json=body).status_code in {403,404}


@pytest.mark.parametrize("frequency,instructions,expected", [
    ("Once daily", "After lunch", ["13:00"]),
    ("Once daily", "Before sleep", ["23:00"]),
    ("Once daily", "30 minutes before breakfast", ["07:30"]),
    ("Once daily", "2 hours after lunch", ["15:00"]),
    ("Twice daily", "After breakfast and after dinner", ["08:00","19:00"]),
    ("After lunch", "", ["13:00"]),
    ("Once daily before bed", "", ["23:00"]),
])
def test_named_meals_and_sleep_use_the_saved_routine(client, frequency, instructions, expected):
    report, _ = manual(client, frequency=frequency, instructions=instructions)
    url = f"/api/reports/{report['id']}"
    timing = client.get(url + "/timing?group=Medication%201").json()
    assert timing["can_schedule"] and timing["times"] == expected
    assert client.post(url + "/reminders", json=reminder(report,times=expected)).status_code == 201


def test_editable_anchors_preserve_exact_stated_gaps_and_detect_conflicts(client):
    report, _ = manual(client, instructions="After lunch")
    assert client.post(f"/api/reports/{report['id']}/reminders", json=reminder(report,times=["13:15"])).status_code == 201
    precise, _ = manual(client, name="Different medicine", instructions="30 minutes before breakfast")
    url = f"/api/reports/{precise['id']}"
    assert client.post(url + "/reminders", json=reminder(precise,times=["08:00"])).status_code == 422
    assert client.post(url + "/reminders", json=reminder(precise,times=["07:30"],timezone="UTC")).status_code == 422
    conflict, _ = manual(client, name="Conflict example", frequency="Every 12 hours", instructions="After breakfast and after dinner")
    assert not client.get(f"/api/reports/{conflict['id']}/timing?group=Medication%201").json()["can_schedule"]
    assert client.post(f"/api/reports/{conflict['id']}/reminders", json=reminder(conflict,times=["08:00","19:00"])).status_code == 422
    prn, _ = manual(client, instructions="As needed after lunch at 13:00")
    assert not client.get(f"/api/reports/{prn['id']}/timing?group=Medication%201").json()["can_schedule"]
    assert client.post(f"/api/reports/{prn['id']}/reminders", json=reminder(prn)).status_code == 422
    unknown, _ = manual(client, name="Unclear gap example", instructions="Half an hour before breakfast")
    assert not client.get(f"/api/reports/{unknown['id']}/timing?group=Medication%201").json()["can_schedule"]
    assert client.post(f"/api/reports/{unknown['id']}/reminders", json=reminder(unknown)).status_code == 422
    mismatch, _ = manual(client, name="Clock conflict example", frequency="08:00", instructions="30 minutes before breakfast")
    assert not client.get(f"/api/reports/{mismatch['id']}/timing?group=Medication%201").json()["can_schedule"]
    assert client.post(f"/api/reports/{mismatch['id']}/reminders", json=reminder(mismatch,times=["08:00"])).status_code == 422


def test_manual_entries_survive_encrypted_restart_export_backup_and_delete(client, tmp_path):
    report, _ = manual(client)
    vault.initialize(store.DATA)
    prefix = f"/api/reports/{report['id']}"
    assert client.get(prefix).json()["fields"] == report["fields"]
    with ZipFile(io.BytesIO(client.get(prefix + "/export").content)) as bundle:
        assert set(bundle.namelist()) == {"report.json","README.txt"}
        assert json.loads(bundle.read("report.json"))["original_file"] is None
    path = tmp_path / "manual.acb"
    backup.create_backup(store.DATA,path,"fictional-manual-backup-pass")
    restored = tmp_path / "restored-manual"
    backup.restore_backup(path,restored,"fictional-manual-backup-pass")
    vault.initialize(restored)
    with sqlite3.connect(":memory:") as db:
        db.deserialize(vault.read(restored / "aftercare.db"))
        payload = json.loads(db.execute("SELECT payload FROM reports WHERE id=?",(report["id"],)).fetchone()[0])
        assert payload["file"] is None and payload["fields"] == report["fields"]
    assert client.request("DELETE",prefix,json={"name":report["name"],"current_password":"fictional-password-123","archive_first":True}).status_code == 200
    assert client.get(prefix).status_code == 404


def test_missing_uploaded_source_cannot_masquerade_as_a_manual_entry(client):
    report = client.post("/api/reports/sample").json()
    report.update(kind="manual",file=None,pages=[])
    with pytest.raises(ValueError,match="Only manually"):
        vault.source_name(report)


@pytest.mark.parametrize("frequency", ["08:00, 25:00", "8 am, 20 pm", "08:99, 20:00"])
def test_invalid_clock_cannot_be_silently_dropped(client, frequency):
    report, _ = manual(client, frequency=frequency)
    url = f"/api/reports/{report['id']}"
    assert not client.get(url + "/timing?group=Medication%201").json()["can_schedule"]
    assert client.post(url + "/reminders", json=reminder(report,times=["08:00"])).status_code == 422


def test_context_does_not_turn_a_diagnosis_into_a_prescribing_reason(client, monkeypatch):
    import httpx
    report = client.post("/api/reports/sample").json()
    with store.connect() as db:
        report["fields"].append({"id":"diagnosis", "group":"Recovery", "label":"Diagnosis", "value":"Headache",
                                 "status":"confirmed", "origin":"manual", "source":None})
        for field in report["fields"]:
            field["status"] = "confirmed"
        report["plan_saved"] = True
        db.execute("UPDATE reports SET payload=? WHERE id=?",(json.dumps(report),report["id"]))
    prefix = f"/api/reports/{report['id']}/medicines/"
    info = client.get(prefix + "info?group=Medication%201").json()
    assert info["reason"] is None and info["context"][0]["value"] == "Headache"
    assert "does not explicitly link" in info["context_notice"]
    linked = client.get(prefix + "info?group=Medication%202").json()
    assert linked["reason"] == "For pain" and linked["reason_origin"] == "document"
    assert "For pain" in linked["reason_source"]["text"]
    def unsupported(*args, **kwargs):
        assert "Headache" in kwargs["json"]["messages"][-1]["content"]
        return httpx.Response(200,json={"message":{"content":'{"fact_ids":[999],"reason":"This antibiotic is for your headache"}'}},request=httpx.Request("POST","http://localhost"))
    monkeypatch.setattr(httpx,"post",unsupported)
    explained = client.post(prefix + "explain?group=Medication%201").json()
    assert explained["reason"] is None and explained["facts"] == info["facts"]


def test_manual_visits_keep_source_followups_and_survive_storage(client, tmp_path):
    prescription = client.post("/api/reports/sample").json()
    medicine, _ = manual(client)
    before = {report["id"] for report in client.get("/api/reports").json()}
    body = {"request_id": str(uuid4()), "title": "Dental check-up", "details": "Fictional clinic", "planned_date": "2026-12-10", "note": "10:30", "confirmed": True}
    response = client.post("/api/visits/manual", json=body)
    assert response.status_code == 201, response.text
    visit_report = response.json()
    assert visit_report["file"] is None and visit_report["pages"] == [] and visit_report["entry_type"] == "visit"
    field = visit_report["fields"][0]
    assert field["origin"] == "manual" and field["source"] is None and field["status"] == "confirmed"
    assert client.post("/api/visits/manual", json=body).json() == visit_report
    assert client.post("/api/visits/manual", json={**body,"title":"Different appointment"}).status_code == 409
    assert client.post("/api/visits/manual", json={**body,"request_id":str(uuid4()),"title":" "}).status_code == 422
    assert client.post("/api/visits/manual", json={**body,"request_id":str(uuid4()),"planned_date":"2026-02-30"}).status_code == 422
    assert before <= {report["id"] for report in client.get("/api/reports").json()}
    patient_id = client.get("/api/care").json()["patients"][0]["id"]
    url = f"/api/care/visits?patient_id={patient_id}"
    rows = client.get(url).json()
    added = next(item for item in rows if item["report_id"] == visit_report["id"])
    assert added["visit"]["planned_date"] == body["planned_date"] and added["visit"]["source_value"] == field["value"]
    assert any(item["report_id"] == prescription["id"] and item["field"]["source"] for item in rows)
    assert client.get(f"/api/reports/{medicine['id']}").json()["fields"] == medicine["fields"]
    vault.initialize(store.DATA)
    assert client.get(url).json() == rows
    with ZipFile(io.BytesIO(client.get(f"/api/reports/{visit_report['id']}/export").content)) as bundle:
        assert json.loads(bundle.read("report.json"))["original_file"] is None
    path = tmp_path / "visits.acb"
    backup.create_backup(store.DATA,path,"fictional-visit-backup-pass")
    restored = tmp_path / "restored-visits"
    backup.restore_backup(path,restored,"fictional-visit-backup-pass")
    vault.initialize(restored)
    with sqlite3.connect(":memory:") as db:
        db.deserialize(vault.read(restored / "aftercare.db"))
        assert db.execute("SELECT planned_date FROM visits WHERE report_id=?", (visit_report["id"],)).fetchone()[0] == body["planned_date"]
    assert client.post(f"/api/reports/{visit_report['id']}/archive").status_code == 200
    assert all(item["report_id"] != visit_report["id"] for item in client.get(url).json())
    assert client.post(f"/api/reports/{visit_report['id']}/restore").status_code == 200
    assert any(item["report_id"] == visit_report["id"] for item in client.get(url).json())


def test_visit_journey_enforces_caretaker_scope_and_revocation(client, caregiver):
    body = {"request_id":str(uuid4()), "title":"User-entered visit", "confirmed":True}
    report = client.post("/api/visits/manual", json=body).json()
    patient, grant = invite(client, "viewer")
    url = f"/api/care/visits?patient_id={patient['id']}"
    assert caregiver.get(url).status_code == 404
    assert caregiver.post(f"/api/care/invitations/{grant}/respond", json={"action":"accept"}).status_code == 200
    assert caregiver.get(url).json()[0]["visit"]["status"] == "planned"
    assert caregiver.post(f"/api/visits/manual?episode_id={report['episode_id']}", json={**body,"request_id":str(uuid4())}).status_code == 404
    field = report["fields"][0]
    change = {"status":"booked","planned_date":"2026-12-10","note":"Fictional booking"}
    assert caregiver.put(f"/api/reports/{report['id']}/visits/{field['id']}", json=change).status_code == 403
    assert client.put(f"/api/reports/{report['id']}/visits/{field['id']}", json=change).status_code == 200
    assert caregiver.get(url).json()[0]["visit"]["planned_date"] == change["planned_date"]
    client.post(f"/api/care/patients/{patient['id']}/invitations/{grant}/revoke")
    assert caregiver.get(url).status_code == 404


def test_multiple_medicines_and_reminders_retain_their_own_sources(client):
    first, _ = manual(client, name="Fictional medicine A")
    second, _ = manual(client, name="Fictional medicine B", frequency="Twice daily")
    for report, times in [(first,["13:00"]),(second,["08:00","20:00"])]:
        response = client.post(f"/api/reports/{report['id']}/reminders", json=reminder(report,times=times))
        assert response.status_code == 201, response.text
    records = {item["id"]:item for item in client.get("/api/reports").json()}
    for report in (first,second):
        assert records[report["id"]]["fields"] == report["fields"]
    patient_id = client.get("/api/care").json()["patients"][0]["id"]
    doses = client.get(f"/api/care/today?patient_id={patient_id}").json()
    assert [(item["name"], item["report_id"]) for item in doses].count(("Fictional medicine B",second["id"])) == 2
    assert any(item["name"] == "Fictional medicine A" and item["report_id"] == first["id"] for item in doses)
    assert client.post(f"/api/reports/{first['id']}/reminders", json=reminder(first)).status_code == 409
