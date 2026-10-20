import json
from datetime import datetime, timedelta, timezone

import pytest

from . import personal, reminders, schedules, store
from .test_sharing import caregiver, invite


def reviewed(client):
    report = client.post("/api/reports/sample?engine=baseline").json()
    current = client.get(f"/api/reports/{report['id']}/overview").json()
    response = client.put(f"/api/reports/{report['id']}/review", json={"revision": current["revision"], "fields": [
        {"id": field["id"], "value": field["value"], "status": "confirmed"} for field in current["fields"]]})
    assert response.status_code == 200, response.text
    return response.json()


def draft(report, **changes):
    today = datetime.now(timezone.utc).date()
    return {"group": "Medication 1", "dose": "1 capsule", "times": ["00:00", "12:00"], "start": today.isoformat(),
            "end": (today + timedelta(days=4)).isoformat(), "timezone": "UTC", "confirmed": True, "revision": report["revision"], **changes}


def active(client):
    report = reviewed(client)
    result = client.post(f"/api/reports/{report['id']}/reminders", json=draft(report))
    assert result.status_code == 201, result.text
    return report, result.json()[0]


def test_personal_setup_is_idempotent_and_keeps_existing_records(client):
    before = client.get("/api/care").json()
    first = client.post("/api/care/personal").json()
    second = client.post("/api/care/personal").json()
    assert first == second
    assert first["personal"]["patient_id"] == before["patients"][0]["id"]
    assert len(first["patients"]) == 1


def test_one_confirmation_preserves_source_and_detects_stale_edits(client):
    report = client.post("/api/reports/sample?engine=baseline").json()
    original = client.get(f"/api/reports/{report['id']}/file").content
    url = f"/api/reports/{report['id']}"
    current = client.get(url + "/overview").json()
    body = {"revision": current["revision"], "fields": [{"id": field["id"], "value": field["value"], "status": "confirmed"} for field in report["fields"]]}
    body["fields"][0]["value"] = "Corrected hospital"
    result = client.put(url + "/review", json=body)
    assert result.status_code == 200
    assert result.json()["plan_saved"]
    assert result.json()["fields"][0]["source"] == report["fields"][0]["source"]
    assert client.get(url + "/file").content == original
    assert client.put(url + "/review", json=body).status_code == 409
    assert len(client.get(url + "/history").json()) == len(report["fields"])


def test_manual_details_are_labeled_and_cannot_replace_existing_source(client):
    report = reviewed(client)
    url = f"/api/reports/{report['id']}"
    response = client.post(url + "/fields", json={"group": "Medication 3", "label": "Name", "value": "User entered medicine"})
    assert response.status_code == 201
    added = response.json()["fields"][-1]
    assert added["origin"] == "manual" and added["source"] is None
    assert not response.json()["plan_saved"]
    assert client.post(url + "/fields", json={"group": "Medication 1", "label": "Name", "value": "Overwrite"}).status_code == 409
    assert client.post(url + "/fields", json={"group": "../../invalid", "label": "Name", "value": "Invalid"}).status_code == 422


def test_user_reminders_need_no_clinician_but_bind_source_and_block_overlap(client):
    report, schedule = active(client)
    assert schedule["status"] == "active" and schedule["authority"] == "personal"
    assert len(schedule["doses"]) == 2
    assert client.get("/api/clinicians").json() == []
    url = f"/api/reports/{report['id']}"
    assert client.post(url + "/reminders", json=draft(report)).status_code == 409
    other = reviewed(client)
    assert client.post(f"/api/reports/{other['id']}/reminders", json=draft(other)).status_code == 409
    field = report["fields"][0]
    client.patch(url + f"/fields/{field['id']}", json={"value": "Correction", "status": "confirmed"})
    assert client.get(url + "/schedules").json()[0]["status"] == "suspended"
    assert client.post(url + f"/schedules/{schedule['id']}/dose", json={"due_at": schedule["doses"][0]["due_at"], "action": "taken"}).status_code == 409


@pytest.mark.parametrize("change", [{"dose": "3 capsules"}, {"times": ["08:00"]}, {"times": ["25:00", "08:00"]}, {"confirmed": False}, {"timezone": "Invalid/Zone"}])
def test_personal_reminders_reject_missing_confirmation_or_changed_instructions(client, change):
    report = reviewed(client)
    assert client.post(f"/api/reports/{report['id']}/reminders", json=draft(report, **change)).status_code == 422


def test_prn_has_no_automatic_fixed_reminder(client):
    report = reviewed(client)
    timing = client.get(f"/api/reports/{report['id']}/timing?group=Medication%202").json()
    assert not timing["can_schedule"] and timing["times"] == []
    assert client.post(f"/api/reports/{report['id']}/reminders", json=draft(report, group="Medication 2", dose="1 tablet", times=["08:00"])).status_code == 422


def test_routine_changes_suggestions_not_existing_reminder_and_intervals_are_preserved(client):
    report, schedule = active(client)
    routine = {"wake": "06:00", "breakfast": "07:00", "lunch": "12:00", "dinner": "18:00", "sleep": "22:00", "timezone": "Asia/Kolkata"}
    assert client.put("/api/care/routine", json=routine).status_code == 200
    assert client.get(f"/api/reports/{report['id']}/timing?group=Medication%201").json()["times"] == ["07:00", "18:00"]
    assert client.get(f"/api/reports/{report['id']}/schedules").json()[0]["payload"]["times"] == ["00:00", "12:00"]
    assert personal.frequency_count("every 8 hours") == (3, "interval:8")


def test_caretaker_updates_delay_preferences_undo_and_revocation(client, caregiver, monkeypatch):
    report, schedule = active(client)
    patient, invitation = invite(client, "viewer")
    caregiver.post(f"/api/care/invitations/{invitation}/respond", json={"action": "accept"})
    today = datetime.now(timezone.utc).replace(hour=0, minute=35, second=0, microsecond=0)
    monkeypatch.setattr(reminders, "now_utc", lambda: today)
    with store.connect() as db:
        midnight = today.replace(minute=0).isoformat()
        db.execute("UPDATE schedules SET created_at=? WHERE id=?", (midnight, schedule["id"]))
        db.execute("UPDATE caregiver_access SET updated_at=? WHERE id=?", (midnight, invitation))
    reminders.collect_unconfirmed(); reminders.collect_unconfirmed()
    updates = caregiver.get("/api/care/notifications").json()
    assert len(updates) == 1 and updates[0]["kind"] == "unconfirmed"
    assert "does not prove" in updates[0]["body"]
    url = f"/api/reports/{report['id']}/schedules/{schedule['id']}/dose"
    action = {"due_at": schedule["doses"][0]["due_at"], "action": "taken"}
    assert caregiver.post(url, json=action).status_code == 403
    assert client.post(url, json=action).status_code == 200
    assert caregiver.get("/api/care/notifications").json()[0]["kind"] == "taken"
    assert client.post(url, json={**action, "action": "undo"}).status_code == 200
    assert caregiver.get("/api/care/notifications").json()[0]["kind"] == "undo"
    assert client.put(f"/api/care/patients/{patient['id']}/invitations/{invitation}/alerts", json={"taken": False,"skipped":False,"unconfirmed":False,"delay_minutes":60}).status_code == 200
    before = len(caregiver.get("/api/care/notifications").json())
    client.post(url, json={**action, "action": "skipped"})
    assert len(caregiver.get("/api/care/notifications").json()) == before
    client.post(f"/api/care/patients/{patient['id']}/invitations/{invitation}/revoke")
    assert caregiver.get("/api/care/notifications").json() == []
    assert caregiver.get(f"/api/care/today?patient_id={patient['id']}").status_code == 404
    assert caregiver.post(f"/api/care/notifications/{updates[0]['id']}/read").status_code == 404


def test_source_info_never_guesses_from_diagnosis_or_similar_name(client, monkeypatch):
    report = reviewed(client)
    prefix = f"/api/reports/{report['id']}/medicines/"
    info = client.get(prefix + "info?group=Medication%201").json()
    assert info["matched"] and info["reason"] is None
    assert info["source_url"].startswith("https://www.nhs.uk/")
    from .medicine_info import reference_name
    assert reference_name("Ibuprofen 400mg tablets") == "ibuprofen"
    assert reference_name("Amoxicillin + clavulanate") is None
    assert reference_name("Amoxycillinx") is None
    import httpx
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: httpx.Response(200, json={"message": {"content": '{"fact_ids":[999],"invented":"Treats every disease"}'}}, request=httpx.Request("POST", "http://localhost")))
    explained = client.post(prefix + "explain?group=Medication%201").json()
    assert explained["facts"] == info["facts"]
    assert "every disease" not in json.dumps(explained)


def test_twelve_hour_clocks_and_conflicting_duration_are_not_silently_changed(client):
    assert personal.prescribed_times("8 am and 8:30 pm") == ["08:00", "20:30"]
    assert personal.prescribed_times("12 am, 12 pm, 23:10") == ["00:00", "12:00", "23:10"]
    report = reviewed(client)
    assert client.post(f"/api/reports/{report['id']}/reminders", json=draft(report, end=(datetime.now(timezone.utc).date()+timedelta(days=8)).isoformat())).status_code == 422


def test_manual_records_also_send_caretaker_status_updates(client, caregiver):
    from uuid import uuid4
    report = reviewed(client)
    _, invitation = invite(client, "viewer")
    caregiver.post(f"/api/care/invitations/{invitation}/respond", json={"action":"accept"})
    result = client.post(f"/api/reports/{report['id']}/medications/log", json={"request_id":str(uuid4()),"group":"Medication 2","status":"taken"})
    assert result.status_code == 201
    assert caregiver.get("/api/care/notifications").json()[0]["kind"] == "taken"
    entry = result.json()["medications"][0]
    client.post(f"/api/reports/{report['id']}/medications/log/{entry['id']}/undo")
    assert caregiver.get("/api/care/notifications").json()[0]["kind"] == "undo"


def test_automatic_extraction_keeps_source_when_local_ai_is_unavailable(client, monkeypatch):
    import httpx
    from . import main
    monkeypatch.setenv("AFTERCARE_AUTO_AI", "1")
    monkeypatch.setattr(main, "baseline", lambda pages: [])
    def unavailable(*args, **kwargs):
        raise httpx.ConnectError("Local model is unavailable")
    monkeypatch.setattr(httpx, "get", unavailable)
    response = client.post("/api/reports/sample")
    assert response.status_code == 200
    report = response.json()
    assert report["fields"] == [] and not report["plan_saved"]
    assert client.get(f"/api/reports/{report['id']}/file").content.startswith(b"%PDF")
    added = client.post(f"/api/reports/{report['id']}/fields", json={"group":"Medication 1", "label":"Name", "value":"Entered from original"})
    assert added.status_code == 201
    assert added.json()["fields"][0]["origin"] == "manual"


def test_phone_details_keep_their_actual_label_and_source():
    from .extraction import baseline
    pages = [{"number":0,"width":600,"height":800,"method":"text","lines":[
        {"text":"Email address: clinic@example.test Phone number: 678-94299","box":[20,30,560,50]},
        {"text":"Hospital phone: +91 98765 43210","box":[20,50,560,70]},
        {"text":"Date of birth: March 5, 1953","box":[20,70,560,90]}]}]
    for line in pages[0]["lines"]:
        line["words"] = [{"text":line["text"], "box":line["box"]}]
    phones = [field for field in baseline(pages) if field.group == "Contacts"]
    assert [(field.label, field.value) for field in phones] == [("Phone Number","678-94299"),("Hospital Phone","+91 98765 43210")]
    assert phones[0].source.text == pages[0]["lines"][0]["text"]


def test_interval_and_explicit_clocks_cannot_be_changed_by_reminder_request(client):
    report = reviewed(client)
    url = f"/api/reports/{report['id']}"
    field = next(field for field in report["fields"] if field["group"] == "Medication 1" and field["label"] == "Frequency")
    for frequency, bad_times in [("every 8 hours", ["08:00","12:00","18:00"]), ("8 am and 8 pm", ["07:00","19:00"])]:
        current = client.get(url + "/overview").json()
        body = {"revision":current["revision"],"fields":[{"id":f["id"],"value":frequency if f["id"] == field["id"] else f["value"],"status":"confirmed"} for f in current["fields"]]}
        confirmed = client.put(url + "/review", json=body).json()
        assert client.post(url + "/reminders", json=draft(confirmed,times=bad_times)).status_code == 422


def test_direct_delete_requires_owner_proof_and_cleans_active_reminders(client, caregiver):
    report, schedule = active(client)
    _, invitation = invite(client, "viewer")
    caregiver.post(f"/api/care/invitations/{invitation}/respond", json={"action":"accept"})
    url = f"/api/reports/{report['id']}"
    proof = {"name":report["name"],"current_password":"fictional-password-123","archive_first":True}
    assert caregiver.request("DELETE", url, json=proof).status_code == 403
    assert client.request("DELETE", url, json={**proof,"current_password":"wrong"}).status_code == 403
    assert client.get(url).status_code == 200
    assert client.request("DELETE", url, json=proof).status_code == 200
    assert client.get(url+"/file").status_code == 404
    with store.connect() as db:
        assert not db.execute("SELECT 1 FROM schedules WHERE id=?", (schedule["id"],)).fetchone()
        assert not db.execute("SELECT 1 FROM care_notifications WHERE report_id=?", (report["id"],)).fetchone()
