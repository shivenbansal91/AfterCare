import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from . import store
from .models import MedicationEntry, VisitUpdate

router = APIRouter(prefix="/api/reports")


def require_report(report_id: str, reviewed: bool = False, db=None):
    report = store.get(report_id, db)
    if not report:
        raise HTTPException(404, "Report not found.")
    if reviewed and not report["plan_saved"]:
        raise HTTPException(409, "Save the reviewed care plan before recording care activity.")
    return report


@router.get("/{report_id}/activity")
def activity(report_id: str):
    require_report(report_id)
    with store.connect() as db:
        entries = [dict(row) for row in db.execute(
            """SELECT medication_entries.*, users.username AS actor_name FROM medication_entries
            LEFT JOIN users ON users.id=actor_id WHERE report_id=? AND voided_at IS NULL ORDER BY occurred_at DESC LIMIT 100""",
            (report_id,),
        )]
        visits = [dict(row) for row in db.execute("""SELECT visits.*,users.username AS actor_name FROM visits
            LEFT JOIN users ON users.id=actor_id WHERE report_id=?""", (report_id,))]
    for entry in entries:
        entry["snapshot"] = json.loads(entry["snapshot"])
    return {"medications": entries, "visits": visits}


@router.post("/{report_id}/medications/log", status_code=201)
def record_medication(report_id: str, entry: MedicationEntry):
    store.require_report_permission(report_id, "record")
    report = require_report(report_id, reviewed=True)
    fields = [field for field in report["fields"] if field["group"] == entry.group]
    if not entry.group.startswith("Medication") or not fields:
        raise HTTPException(404, "Medication not found.")
    if any(field["status"] != "confirmed" for field in fields) or not any(field["label"] == "Name" for field in fields):
        raise HTTPException(409, "Review every available field for this medication before logging it.")
    if len({field["label"] for field in fields}) != len(fields):
        raise HTTPException(409, "This medication has repeated fields. Clarify the conflicting instructions before logging it.")
    now = datetime.now(timezone.utc)
    occurred = entry.occurred_at.astimezone(timezone.utc) if entry.occurred_at else now
    if occurred > now + timedelta(minutes=5):
        raise HTTPException(422, "Record medication activity after it happens.")
    snapshot = {field["label"]: field["value"] for field in fields}
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        patient_id = store.require_report_permission(report_id, "record", db)
        current = require_report(report_id, reviewed=True, db=db)
        if current["fields"] != report["fields"]:
            raise HTTPException(409, "The instructions changed. Refresh and check them before recording activity.")
        result = db.execute("""INSERT OR IGNORE INTO medication_entries
            (id,request_id,report_id,medication_group,status,occurred_at,note,snapshot,created_at,actor_id)
            VALUES (?,?,?,?,?,?,?,?,?,?)""", (
            uuid4().hex, str(entry.request_id), report_id, entry.group, entry.status,
            occurred.isoformat(), entry.note, json.dumps(snapshot), now.isoformat(), store.current_user.get(),
        ))
        saved = db.execute("SELECT * FROM medication_entries WHERE request_id=?", (str(entry.request_id),)).fetchone()
        if (saved["report_id"], saved["medication_group"], saved["status"], saved["note"], saved["actor_id"]) != (report_id, entry.group, entry.status, entry.note, store.current_user.get()):
            raise HTTPException(409, "This request was already used for a different record.")
        if entry.occurred_at and saved["occurred_at"] != occurred.isoformat():
            raise HTTPException(409, "This request was already used for a different time.")
        if result.rowcount:
            from .care import notify_caregivers
            notify_caregivers(db, patient_id, {"id": "manual:" + saved["id"], "report_id": report_id, "payload": {"name": snapshot.get("Name", entry.group)}}, occurred.isoformat(), entry.status)
            store.audit(db, patient_id, "medication_recorded", saved["id"], entry.status)
    return activity(report_id)


@router.post("/{report_id}/medications/log/{entry_id}/undo")
def undo_medication(report_id: str, entry_id: str):
    require_report(report_id)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        patient_id = store.require_report_permission(report_id, "record", db)
        entry = db.execute("SELECT id,actor_id,voided_at,occurred_at,snapshot FROM medication_entries WHERE id=? AND report_id=?", (entry_id, report_id)).fetchone()
        if not entry:
            raise HTTPException(404, "Medication record not found.")
        if store.patient_role(patient_id, db) != "owner" and entry["actor_id"] != store.current_user.get():
            raise HTTPException(403, "You can only undo your own medication records.")
        if not entry["voided_at"]:
            db.execute("UPDATE medication_entries SET voided_at=?,voided_by=? WHERE id=?",
                       (datetime.now(timezone.utc).isoformat(), store.current_user.get(), entry_id))
            from .care import notify_caregivers
            notify_caregivers(db, patient_id, {"id": "manual:" + entry_id, "report_id": report_id, "payload": {"name": json.loads(entry["snapshot"]).get("Name", "Medicine")}}, entry["occurred_at"], "undo")
            store.audit(db, patient_id, "medication_undone", entry_id)
    return activity(report_id)


@router.put("/{report_id}/visits/{field_id}")
def update_visit(report_id: str, field_id: str, change: VisitUpdate):
    store.require_report_permission(report_id, "record")
    report = require_report(report_id, reviewed=True)
    field = next((f for f in report["fields"] if f["id"] == field_id and f["group"] == "Visits"), None)
    if not field:
        raise HTTPException(404, "Visit or test not found.")
    if field["status"] != "confirmed":
        raise HTTPException(409, "Review this instruction before tracking it.")
    if change.status == "booked" and not change.planned_date:
        raise HTTPException(422, "Choose the date you booked.")
    if change.status == "planned" and change.planned_date:
        raise HTTPException(422, "Use booked when adding an appointment date.")
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        patient_id = store.require_report_permission(report_id, "record", db)
        current = require_report(report_id, reviewed=True, db=db)
        if current["fields"] != report["fields"]:
            raise HTTPException(409, "The instructions changed. Refresh and check them before recording activity.")
        db.execute("""INSERT INTO visits (report_id,field_id,status,planned_date,note,source_value,updated_at,actor_id)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(report_id,field_id) DO UPDATE SET
                status=excluded.status, planned_date=excluded.planned_date, note=excluded.note,
                source_value=excluded.source_value, updated_at=excluded.updated_at, actor_id=excluded.actor_id""", (
            report_id, field_id, change.status,
            change.planned_date.isoformat() if change.planned_date else None,
            change.note, field["value"], datetime.now(timezone.utc).isoformat(), store.current_user.get(),
        ))
        store.audit(db, patient_id, "visit_updated", field_id, change.status)
    return activity(report_id)
