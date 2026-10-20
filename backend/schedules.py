import hashlib
import json
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException
from pydantic import AwareDatetime, BaseModel, Field, model_validator

from . import store

router = APIRouter(prefix="/api")


class ScheduleDraft(BaseModel):
    group: str = Field(min_length=1, max_length=100)
    clinician_id: str
    dose: str = Field(min_length=1, max_length=200)
    times: list[str] = Field(min_length=1, max_length=8)
    start: date
    end: date
    timezone: str = Field(max_length=100)
    consent: Literal[True]

    @model_validator(mode="after")
    def validate_schedule(self):
        if not self.dose.strip():
            raise ValueError("Enter the exact prescribed dose.")
        if any(not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", t) for t in self.times):
            raise ValueError("Use 24-hour times, for example 08:30.")
        if len(set(self.times)) != len(self.times):
            raise ValueError("Remove repeated times.")
        if not 0 <= (self.end - self.start).days <= 365:
            raise ValueError("Choose an end date within one year of the start date.")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError:
            raise ValueError("Choose a valid IANA time zone.")
        self.times.sort()
        return self


class Decision(BaseModel):
    decision: Literal["approved", "rejected"]
    note: str = Field(min_length=10, max_length=2000)
    fingerprint: str
    attestation: Literal[True]


class DoseAction(BaseModel):
    due_at: AwareDatetime
    action: Literal["taken", "skipped", "snooze", "undo"]
    note: str = Field(default="", max_length=500)


class Revocation(BaseModel):
    reason: str = Field(min_length=10, max_length=2000)


def now_utc():
    return datetime.now(timezone.utc)


def fingerprint(report, db):
    # The review revision prevents reverting a correction from reviving an old approval.
    revision = db.execute("SELECT COALESCE(MAX(id),0) FROM reviews WHERE report_id=?", (report["id"],)).fetchone()[0]
    content = {"fields": report["fields"], "file": report["file"], "revision": revision}
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


def clinician(db, user_id):
    row = db.execute("SELECT * FROM clinicians WHERE user_id=? AND active=1 AND valid_until>?",
                     (user_id, now_utc().isoformat())).fetchone()
    return dict(row) if row else None


def raw_report(db, report_id):
    row = db.execute("SELECT payload FROM reports WHERE id=? AND NOT EXISTS (SELECT 1 FROM report_archives WHERE report_id=?)",
                     (report_id, report_id)).fetchone()
    return json.loads(row[0]) if row else None


def clinical_report(db, report_id):
    credential = clinician(db, store.current_user.get())
    consent = db.execute("SELECT 1 FROM schedules WHERE report_id=? AND clinician_id=? AND consent=1 AND status IN ('requested','approved')",
                         (report_id, store.current_user.get())).fetchone()
    report = raw_report(db, report_id)
    if not credential or not consent or not report or (credential["demo"] and not report["sample"]):
        return None
    return report


def suspend(db, report_id, reason):
    db.execute("UPDATE schedules SET status='suspended',reason=? WHERE report_id=? AND status IN ('requested','approved','active')",
               (reason, report_id))


def eligibility(db, schedule):
    report = raw_report(db, schedule["report_id"])
    if not schedule["consent"]:
        return "This reminder was stopped."
    if not report:
        return "The report is unavailable or archived."
    if schedule.get("authority") != "personal":
        credential = clinician(db, schedule["clinician_id"])
        if not credential:
            return "Clinician credentials expired or were revoked."
        if credential["demo"] and not report["sample"]:
            return "A demonstration clinician cannot approve an uploaded patient document."
    if not report["plan_saved"] or fingerprint(report, db) != schedule["fingerprint"]:
        return "The report changed. Reconfirm its details and reminder times."
    return None


def read_schedule(db, row):
    schedule = dict(row)
    schedule["payload"] = json.loads(schedule["payload"])
    if schedule["status"] in {"approved", "requested", "active"}:
        reason = eligibility(db, schedule)
        if reason:
            db.execute("UPDATE schedules SET status='suspended',reason=? WHERE id=?", (reason, schedule["id"]))
            schedule.update(status="suspended", reason=reason)
    return schedule


def occurrence_times(payload, day):
    if not payload["start"] <= day.isoformat() <= payload["end"]:
        return []
    zone = ZoneInfo(payload["timezone"])
    result = []
    for clock in payload["times"]:
        local = datetime.combine(day, time.fromisoformat(clock), zone)
        utc = local.astimezone(timezone.utc)
        # A skipped DST clock has no occurrence; an ambiguous clock occurs once (fold=0).
        if utc.astimezone(zone).replace(tzinfo=None) == local.replace(tzinfo=None):
            result.append(utc.isoformat())
    return result


def doses(db, schedule, day=None):
    payload = schedule["payload"]
    day = day or now_utc().astimezone(ZoneInfo(payload["timezone"])).date()
    result = []
    for due in occurrence_times(payload, day):
        event = db.execute("SELECT * FROM scheduled_doses WHERE schedule_id=? AND due_at=?", (schedule["id"], due)).fetchone()
        value = dict(event) if event else {}
        result.append({"due_at": due, "status": value.get("status", "pending"),
                       "note": value.get("note", ""), "actor_id": value.get("actor_id"),
                       "snoozed_until": value.get("snoozed_until"), "recorded_at": value.get("recorded_at")})
    return result


@router.get("/clinicians")
def directory():
    with store.connect() as db:
        return [dict(row) for row in db.execute("""SELECT user_id,display_name,registration,demo,valid_until
            FROM clinicians WHERE active=1 AND valid_until>? ORDER BY display_name""", (now_utc().isoformat(),))]


@router.get("/clinical/queue")
def clinical_queue():
    with store.connect() as db:
        identity = clinician(db, store.current_user.get())
        result = []
        if identity:
            for row in db.execute("SELECT * FROM schedules WHERE clinician_id=? AND consent=1 ORDER BY created_at DESC", (identity["user_id"],)).fetchall():
                schedule = read_schedule(db, row)
                if schedule["status"] in {"requested", "approved"}:
                    report = clinical_report(db, schedule["report_id"])
                    if report:
                        result.append({"schedule": schedule, "report": report})
        return {"identity": identity, "requests": result}


@router.get("/reports/{report_id}/schedules")
def list_schedules(report_id: str, day: date | None = None):
    with store.connect() as db:
        if not store.get(report_id, db):
            raise HTTPException(404, "Report not found.")
        return list_schedules_in_transaction(db, report_id, day)


@router.post("/reports/{report_id}/schedules", status_code=201)
def request_schedule(report_id: str, draft: ScheduleDraft):
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        patient_id = store.require_report_permission(report_id, "edit", db)
        report = store.get(report_id, db)
        fields = [f for f in report["fields"] if f["group"] == draft.group]
        if not report["plan_saved"] or not draft.group.startswith("Medication") or not fields or any(f["status"] != "confirmed" for f in fields):
            raise HTTPException(409, "Save a reviewed plan and resolve this medication's fields first.")
        if not any(f["label"] == "Name" and f["value"].strip() for f in fields) or len({f["label"] for f in fields}) != len(fields):
            raise HTTPException(409, "Resolve missing names or conflicting fields first.")
        reviewer = clinician(db, draft.clinician_id)
        if not reviewer or (reviewer["demo"] and not report["sample"]):
            raise HTTPException(422, "Select an authorized clinician. Demo clinicians can only review built-in fictional samples.")
        if draft.clinician_id == store.current_user.get():
            raise HTTPException(403, "A different clinician must review your request.")
        if draft.end < now_utc().astimezone(ZoneInfo(draft.timezone)).date():
            raise HTTPException(422, "This proposed schedule has already ended.")
        if db.execute("SELECT 1 FROM schedules WHERE report_id=? AND medication_group=? AND status IN ('approved','requested')", (report_id, draft.group)).fetchone():
            raise HTTPException(409, "Stop the existing schedule or request before replacing it.")
        payload = draft.model_dump(mode="json", exclude={"consent", "clinician_id"})
        payload["source"] = fields
        payload["name"] = next(f["value"] for f in fields if f["label"] == "Name")
        identity = uuid4().hex
        db.execute("""INSERT INTO schedules(id,report_id,medication_group,owner_id,clinician_id,payload,fingerprint,status,
            consent,created_at,reason) VALUES (?,?,?,?,?,?,?,'requested',1,?,'')""",
            (identity, report_id, draft.group, store.current_user.get(), draft.clinician_id, json.dumps(payload), fingerprint(report, db), now_utc().isoformat()))
        store.audit(db, patient_id, "clinical_review_requested", report_id, identity)
    return list_schedules(report_id)


@router.post("/clinical/schedules/{schedule_id}/decision")
def decide(schedule_id: str, decision: Decision):
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM schedules WHERE id=? AND clinician_id=?", (schedule_id, store.current_user.get())).fetchone()
        if not row or not clinical_report(db, row["report_id"]):
            raise HTTPException(404, "Clinical request not found.")
        schedule = read_schedule(db, row)
        if schedule["status"] != "requested" or decision.fingerprint != schedule["fingerprint"]:
            raise HTTPException(409, "This request changed or is no longer pending. Refresh the clinical queue.")
        if eligibility(db, schedule):
            raise HTTPException(409, "The source or clinician authorization changed.")
        db.execute("UPDATE schedules SET status=?,decision_at=?,decision_note=? WHERE id=?",
                   (decision.decision, now_utc().isoformat(), decision.note, schedule_id))
        patient_id = db.execute("SELECT patient_id FROM report_access JOIN episodes ON episode_id=episodes.id WHERE report_id=?", (schedule["report_id"],)).fetchone()[0]
        store.audit(db, patient_id, "clinical_" + decision.decision, schedule["report_id"], schedule_id)
    return clinical_queue()


@router.post("/clinical/schedules/{schedule_id}/revoke")
def revoke_approval(schedule_id: str, change: Revocation):
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM schedules WHERE id=? AND clinician_id=?", (schedule_id, store.current_user.get())).fetchone()
        if not row or not clinical_report(db, row["report_id"]):
            raise HTTPException(404, "Clinical request not found.")
        db.execute("UPDATE schedules SET status='suspended',consent=0,reason=? WHERE id=?", (change.reason, schedule_id))
        patient_id = db.execute("SELECT patient_id FROM episodes JOIN report_access ON episode_id=episodes.id WHERE report_id=?", (row["report_id"],)).fetchone()[0]
        store.audit(db, patient_id, "clinical_approval_revoked", row["report_id"], json.dumps({"schedule": schedule_id, "reason": change.reason}))
    return clinical_queue()


@router.post("/reports/{report_id}/schedules/{schedule_id}/stop")
def stop_schedule(report_id: str, schedule_id: str):
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        patient_id = store.require_report_permission(report_id, "edit", db)
        result = db.execute("UPDATE schedules SET status='stopped',consent=0,reason='Stopped by owner.' WHERE id=? AND report_id=?",
                            (schedule_id, report_id))
        if not result.rowcount:
            raise HTTPException(404, "Schedule not found.")
        store.audit(db, patient_id, "schedule_stopped", report_id, schedule_id)
    return list_schedules(report_id)


@router.post("/reports/{report_id}/schedules/{schedule_id}/dose")
def record_dose(report_id: str, schedule_id: str, action: DoseAction):
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        patient_id = store.require_report_permission(report_id, "record", db)
        row = db.execute("SELECT * FROM schedules WHERE id=? AND report_id=?", (schedule_id, report_id)).fetchone()
        if not row:
            raise HTTPException(404, "Schedule not found.")
        schedule = read_schedule(db, row)
        if schedule["status"] not in {"approved", "active"} or eligibility(db, schedule):
            raise HTTPException(409, "This reminder is not active. Reconfirm the prescription overview and times.")
        due = action.due_at.astimezone(timezone.utc)
        day = due.astimezone(ZoneInfo(schedule["payload"]["timezone"])).date()
        if due.isoformat() not in occurrence_times(schedule["payload"], day) or due > now_utc():
            raise HTTPException(422, "Choose an existing dose after its scheduled time.")
        previous = db.execute("SELECT * FROM scheduled_doses WHERE schedule_id=? AND due_at=?", (schedule_id, due.isoformat())).fetchone()
        if action.action == "undo":
            if not previous or previous["status"] == "pending":
                raise HTTPException(409, "There is no completed record to undo.")
            if store.patient_role(patient_id, db) != "owner" and previous["actor_id"] != store.current_user.get():
                raise HTTPException(403, "You can only undo your own dose records.")
        elif previous and previous["status"] != "pending":
            if previous["status"] == action.action and previous["note"] == action.note:
                return list_schedules_in_transaction(db, report_id)
            raise HTTPException(409, "This dose is already recorded. Undo it before correcting it.")
        status = action.action if action.action in {"taken", "skipped"} else "pending"
        snoozed = (now_utc() + timedelta(minutes=10)).isoformat() if action.action == "snooze" else None
        db.execute("""INSERT INTO scheduled_doses VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(schedule_id,due_at) DO UPDATE SET
            status=excluded.status,note=excluded.note,actor_id=excluded.actor_id,recorded_at=excluded.recorded_at,snoozed_until=excluded.snoozed_until""",
            (schedule_id, due.isoformat(), status, action.note, store.current_user.get(), now_utc().isoformat(), snoozed, json.dumps(schedule["payload"])))
        from .care import notify_caregivers
        if action.action != "snooze":
            notify_caregivers(db, patient_id, schedule, due.isoformat(), action.action)
        store.audit(db, patient_id, "dose_" + action.action, report_id,
                    json.dumps({"schedule": schedule_id, "due": due.isoformat(), "previous": dict(previous) if previous else None, "note": action.note}))
        return list_schedules_in_transaction(db, report_id)


def list_schedules_in_transaction(db, report_id, day=None):
    result = []
    for row in db.execute("SELECT schedules.*,COALESCE(display_name,'Personal reminder') AS clinician_name,COALESCE(demo,0) AS demo FROM schedules LEFT JOIN clinicians ON user_id=clinician_id WHERE report_id=? ORDER BY created_at DESC", (report_id,)).fetchall():
        schedule = read_schedule(db, row)
        schedule["doses"] = doses(db, schedule, day) if schedule["status"] in {"approved", "active"} else []
        schedule["history"] = [dict(event) for event in db.execute("SELECT due_at,status,note,actor_id,recorded_at,username AS actor_name FROM scheduled_doses LEFT JOIN users ON users.id=actor_id WHERE schedule_id=? ORDER BY due_at DESC LIMIT 100", (schedule["id"],))]
        result.append(schedule)
    return result
