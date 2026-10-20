import io
import json
from zipfile import ZipFile

import pytest

from . import store
from .test_accounts import other_client
from .test_sharing import caregiver, event, invite, reviewed


def mark_archived(report_id):
    with store.connect() as db:
        db.execute("INSERT INTO report_archives VALUES (?, '2026-10-18', 'test')", (report_id,))


@pytest.mark.parametrize("role", ["viewer", "recorder"])
def test_archive_blocks_every_surface_and_restore_preserves_records(client, caregiver, role):
    report = reviewed(client)
    prefix = f"/api/reports/{report['id']}"
    field = next(f for f in report["fields"] if f["group"] == "Visits")
    entry = client.post(prefix + "/medications/log", json=event()).json()["medications"][0]
    client.put(f"{prefix}/visits/{field['id']}", json={"status": "booked", "planned_date": "2026-11-02", "note": "Keep this booking"})
    original = client.get(prefix + "/file").content
    history = client.get(prefix + "/history").json()
    activity = client.get(prefix + "/activity").json()
    patient, invitation = invite(client, role)
    caregiver.post(f"/api/care/invitations/{invitation}/respond", json={"action": "accept"})
    for path in ["archive", "restore"]:
        assert caregiver.post(f"{prefix}/{path}").status_code == 403
    assert caregiver.get(prefix + "/export").status_code == 403
    for _ in range(2):
        assert client.post(prefix + "/archive").status_code == 200
    assert len(client.get("/api/reports/archived").json()) == 1
    assert caregiver.get("/api/reports/archived").json() == []
    for reader in (client, caregiver):
        assert reader.get("/api/reports").json() == []
        for suffix in ["", "/file", "/pages/0", "/history", "/plan", "/activity", "/export"]:
            assert reader.get(prefix + suffix).status_code == 404
        for suffix in ["/plan", "/reread", f"/medications/log/{entry['id']}/undo"]:
            assert reader.post(prefix + suffix).status_code == 404
        assert reader.post(prefix + "/medications/log", json=event()).status_code == 404
        assert reader.put(f"{prefix}/visits/{field['id']}", json={"status": "completed"}).status_code == 404
        assert reader.patch(f"{prefix}/fields/{field['id']}", json={"status": "rejected", "value": "changed"}).status_code == 404
    assert client.post(prefix + "/restore").json()["plan_saved"] is True
    assert client.get("/api/reports/archived").json() == []
    assert client.get(prefix + "/file").content == original
    assert client.get(prefix + "/history").json() == history
    assert client.get(prefix + "/activity").json() == activity
    assert caregiver.get(prefix).status_code == 200
    audit = client.get(f"/api/care/patients/{patient['id']}/access-history").json()
    assert sum(e["action"] == "report_archived" for e in audit) == 1
    assert sum(e["action"] == "report_restored" for e in audit) == 1


def test_unrelated_account_cannot_manage_or_list_archives(client):
    report = reviewed(client)
    visitor = other_client()
    visitor.post("/api/auth/register", json={"username": "outsider", "password": "another-password-123"})
    prefix = f"/api/reports/{report['id']}"
    for state in ("active", "archived"):
        assert visitor.get(prefix + "/export").status_code == 404
        assert visitor.get("/api/reports/archived").json() == []
        for action in ("archive", "restore"):
            assert visitor.post(f"{prefix}/{action}").status_code == 404
        if state == "active":
            client.post(prefix + "/archive")


def test_restore_does_not_reinstate_revoked_caregiver(client, caregiver):
    report = reviewed(client)
    patient, invitation = invite(client, "recorder")
    caregiver.post(f"/api/care/invitations/{invitation}/respond", json={"action": "accept"})
    prefix = f"/api/reports/{report['id']}"
    client.post(prefix + "/archive")
    client.post(f"/api/care/patients/{patient['id']}/invitations/{invitation}/revoke")
    assert client.post(prefix + "/restore").status_code == 200
    assert caregiver.get(prefix + "/file").status_code == 404


def test_export_is_complete_scoped_and_has_safe_zip_names(client):
    report = reviewed(client)
    prefix = f"/api/reports/{report['id']}"
    original = client.get(prefix + "/file").content
    logged = client.post(prefix + "/medications/log", json=event(note="Preserve undone event")).json()["medications"][0]
    client.post(f"{prefix}/medications/log/{logged['id']}/undo")
    visit = next(f for f in report["fields"] if f["group"] == "Visits")
    client.put(f"{prefix}/visits/{visit['id']}", json={"status": "completed", "note": "Preserve visit"})
    other = reviewed(client)
    assert client.post(f"/api/reports/{other['id']}/medications/log", json=event()).status_code == 201
    with store.connect() as db:
        payload = json.loads(db.execute("SELECT payload FROM reports WHERE id=?", (report["id"],)).fetchone()[0])
        payload["name"] = '../../unsafe\\name\r\n.pdf'
        db.execute("UPDATE reports SET payload=? WHERE id=?", (json.dumps(payload), report["id"]))
        password_hash = db.execute("SELECT password FROM users").fetchone()[0]
        session_hash = db.execute("SELECT token FROM sessions").fetchone()[0]
    response = client.get(prefix + "/export")
    assert response.status_code == 200
    assert response.headers["content-disposition"] == 'attachment; filename="aftercare-report.zip"'
    assert response.headers["cache-control"] == "no-store"
    with ZipFile(io.BytesIO(response.content)) as bundle:
        assert set(bundle.namelist()) == {"original.pdf", "report.json", "README.txt"}
        assert bundle.read("original.pdf") == original
        raw = bundle.read("report.json")
        exported = json.loads(raw)
        assert password_hash.encode() not in raw and session_hash.encode() not in raw
        assert other["id"].encode() not in raw
        assert exported["report"]["plan_saved"] is True
        assert len(exported["reviews"]) == len(report["fields"])
        assert exported["reviews"][0]["before"]["source"] == exported["reviews"][0]["after"]["source"]
        assert exported["medications"][0]["voided_at"]
        assert exported["medications"][0]["voided_by_name"] == "test-owner"
        assert exported["medications"][0]["snapshot"]["Name"]
        assert exported["visits"][0]["note"] == "Preserve visit"
        assert exported["audit"][-1]["action"] == "report_exported"
        assert "not an account backup" in bundle.read("README.txt").decode()


@pytest.mark.parametrize("operation", ["review", "plan", "record", "reread"])
def test_archive_between_read_and_write_cannot_change_report(client, monkeypatch, operation):
    report = reviewed(client)
    prefix = f"/api/reports/{report['id']}"
    if operation == "reread":
        with store.connect() as db:
            payload = dict(report, fields=[], plan_saved=False)
            db.execute("UPDATE reports SET payload=? WHERE id=?", (json.dumps(payload), report["id"]))
    before = client.get(prefix).json()
    if operation in {"review", "plan", "reread"}:
        method = "review" if operation == "review" else "save"
        original = getattr(store, method)

        def archive_before_save(*args, **kwargs):
            mark_archived(report["id"])
            return original(*args, **kwargs)

        monkeypatch.setattr(store, method, archive_before_save)
    else:
        original = store.get

        def archive_after_read(report_id, db=None):
            result = original(report_id, db)
            if db is None:
                mark_archived(report_id)
            return result

        monkeypatch.setattr(store, "get", archive_after_read)
    if operation == "review":
        response = client.patch(f"{prefix}/fields/{report['fields'][0]['id']}", json={"status": "confirmed", "value": "Wrong"})
    elif operation == "record":
        response = client.post(prefix + "/medications/log", json=event())
    else:
        response = client.post(prefix + ("/reread" if operation == "reread" else "/plan"))
    assert response.status_code == 404
    with store.connect() as db:
        assert json.loads(db.execute("SELECT payload FROM reports WHERE id=?", (report["id"],)).fetchone()[0]) == before
        assert db.execute("SELECT COUNT(*) FROM medication_entries").fetchone()[0] == 0


def test_plan_save_cannot_overwrite_a_concurrent_correction(client, monkeypatch):
    report = reviewed(client)
    original = store.save

    def correct_before_save(updated, **kwargs):
        with store.connect() as db:
            current = json.loads(db.execute("SELECT payload FROM reports WHERE id=?", (report["id"],)).fetchone()[0])
            current["fields"][0]["value"] = "New reviewed value"
            current["plan_saved"] = False
            db.execute("UPDATE reports SET payload=? WHERE id=?", (json.dumps(current), report["id"]))
        return original(updated, **kwargs)

    monkeypatch.setattr(store, "save", correct_before_save)
    assert client.post(f"/api/reports/{report['id']}/plan").status_code == 409
    result = client.get(f"/api/reports/{report['id']}").json()
    assert result["fields"][0]["value"] == "New reviewed value" and not result["plan_saved"]


def test_export_refuses_missing_source_without_a_partial_download(client):
    report = reviewed(client)
    (store.DATA / report["file"]).unlink()
    response = client.get(f"/api/reports/{report['id']}/export")
    assert response.status_code == 409
    assert "original file is missing" in response.json()["detail"]


@pytest.mark.parametrize("same_field", [False, True])
def test_review_preserves_concurrent_corrections_and_source_evidence(client, monkeypatch, same_field):
    report = reviewed(client)
    field = report["fields"][0]
    index = 0 if same_field else 1
    original = store.review

    def correct_before_review(updated, edited, before):
        with store.connect() as db:
            current = json.loads(db.execute("SELECT payload FROM reports WHERE id=?", (report["id"],)).fetchone()[0])
            current["fields"][index]["value"] = "Concurrent correction"
            current["plan_saved"] = False
            db.execute("UPDATE reports SET payload=? WHERE id=?", (json.dumps(current), report["id"]))
        return original(updated, edited, before)

    monkeypatch.setattr(store, "review", correct_before_review)
    prefix = f"/api/reports/{report['id']}"
    response = client.patch(f"{prefix}/fields/{field['id']}", json={"status": "confirmed", "value": "My correction"})
    assert response.status_code == (409 if same_field else 200)
    result = client.get(prefix).json()
    assert result["fields"][index]["value"] == "Concurrent correction"
    assert result["fields"][0]["source"] == field["source"]
    assert not result["plan_saved"]
    history = client.get(prefix + "/history").json()
    assert len(history) == len(report["fields"]) + (0 if same_field else 1)
    if not same_field:
        assert result["fields"][0]["value"] == "My correction"
