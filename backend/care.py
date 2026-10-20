import json
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import store

router = APIRouter(prefix="/api/care")


class Patient(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class Episode(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    started: date


class Contact(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    role: str = Field(min_length=1, max_length=80)
    phone: str = Field(min_length=3, max_length=30, pattern=r"^\+?[0-9 ()-]+$")
    note: str = Field(default="", max_length=300)


class Invitation(BaseModel):
    username: str = Field(min_length=3, max_length=40, pattern=r"^[a-zA-Z0-9_-]+$")
    role: Literal["viewer", "recorder"] = "viewer"
    taken: bool = True
    skipped: bool = True
    unconfirmed: bool = True
    delay_minutes: int = Field(default=30, ge=5, le=1440)


class AlertPreferences(BaseModel):
    taken: bool
    skipped: bool
    unconfirmed: bool
    delay_minutes: int = Field(ge=5, le=1440)


class InvitationResponse(BaseModel):
    action: Literal["accept", "decline"]


def require_patient(patient_id: str):
    with store.connect() as db:
        row = db.execute("SELECT * FROM patients WHERE id=? AND owner_id=?",
                         (patient_id, store.current_user.get())).fetchone()
    if not row:
        raise HTTPException(404, "Patient profile not found.")
    return dict(row)


def require_episode(episode_id: str):
    with store.connect() as db:
        row = db.execute("""SELECT episodes.* FROM episodes JOIN patients ON patient_id=patients.id
            WHERE episodes.id=? AND owner_id=?""", (episode_id, store.current_user.get())).fetchone()
    if not row:
        raise HTTPException(404, "Recovery episode not found.")
    return dict(row)


@router.get("")
def workspace():
    with store.connect() as db:
        patients = [dict(row) for row in db.execute("""SELECT patients.id,name,users.username AS owner_username
            FROM patients JOIN users ON users.id=owner_id WHERE owner_id=? OR EXISTS (
                SELECT 1 FROM caregiver_access WHERE patient_id=patients.id AND recipient_id=? AND status='active')
            ORDER BY patients.rowid""", (store.current_user.get(), store.current_user.get()))]
        for patient in patients:
            patient["access_role"] = store.patient_role(patient["id"], db)
            patient["episodes"] = [dict(row) for row in db.execute("SELECT * FROM episodes WHERE patient_id=? ORDER BY started DESC,rowid DESC", (patient["id"],))]
            patient["contacts"] = [dict(row) for row in db.execute("SELECT * FROM contacts WHERE patient_id=? ORDER BY rowid", (patient["id"],))]
            patient["sharing"] = [dict(row) for row in db.execute("""SELECT caregiver_access.id, username, role,
                CASE WHEN status='pending' AND expires_at<=? THEN 'expired' ELSE status END AS status, expires_at
                FROM caregiver_access JOIN users ON users.id=recipient_id WHERE patient_id=? ORDER BY created_at DESC""",
                (datetime.now(timezone.utc).isoformat(), patient["id"]))] if patient["access_role"] == "owner" else []
        for patient in patients:
            for grant in patient["sharing"]:
                settings = db.execute("SELECT taken,skipped,unconfirmed,delay_minutes FROM caregiver_alerts WHERE grant_id=?", (grant["id"],)).fetchone()
                grant["alerts"] = dict(settings) if settings else {"taken": False, "skipped": False, "unconfirmed": False, "delay_minutes": 30}
        invitations = [dict(row) for row in db.execute("""SELECT caregiver_access.id, name AS patient_name,
            users.username AS owner_username, role, expires_at FROM caregiver_access
            JOIN patients ON patients.id=patient_id JOIN users ON users.id=owner_id
            WHERE recipient_id=? AND status='pending' AND expires_at>? ORDER BY created_at DESC""",
            (store.current_user.get(), datetime.now(timezone.utc).isoformat()))]
        first_owner = db.execute("SELECT id FROM users ORDER BY rowid LIMIT 1").fetchone()
        legacy = db.execute("SELECT COUNT(*) FROM reports WHERE id NOT IN (SELECT report_id FROM report_access)").fetchone()[0]
    return {"patients": patients, "invitations": invitations, "legacy_count": legacy if first_owner and first_owner[0] == store.current_user.get() else 0}


@router.post("/patients", status_code=201)
def add_patient(body: Patient):
    if not body.name.strip():
        raise HTTPException(422, "Enter the patient's name.")
    with store.connect() as db:
        db.execute("INSERT INTO patients VALUES (?,?,?)", (uuid4().hex, store.current_user.get(), body.name.strip()))
    return workspace()


@router.post("/patients/{patient_id}/episodes", status_code=201)
def add_episode(patient_id: str, body: Episode):
    require_patient(patient_id)
    if not body.title.strip():
        raise HTTPException(422, "Enter a recovery title.")
    with store.connect() as db:
        db.execute("INSERT INTO episodes VALUES (?,?,?,?)", (uuid4().hex, patient_id, body.title.strip(), body.started.isoformat()))
    return workspace()


@router.post("/patients/{patient_id}/contacts", status_code=201)
def add_contact(patient_id: str, body: Contact):
    require_patient(patient_id)
    if not body.name.strip() or not body.role.strip() or sum(c.isdigit() for c in body.phone) < 3:
        raise HTTPException(422, "Enter a name, relationship and phone number.")
    with store.connect() as db:
        db.execute("INSERT INTO contacts VALUES (?,?,?,?,?,?)",
                   (uuid4().hex, patient_id, body.name.strip(), body.role.strip(), body.phone, body.note.strip()))
    return workspace()


@router.delete("/patients/{patient_id}/contacts/{contact_id}")
def remove_contact(patient_id: str, contact_id: str):
    require_patient(patient_id)
    with store.connect() as db:
        result = db.execute("DELETE FROM contacts WHERE id=? AND patient_id=?", (contact_id, patient_id))
        if not result.rowcount:
            raise HTTPException(404, "Contact not found.")
    return workspace()


@router.post("/episodes/{episode_id}/import-local")
def import_local(episode_id: str):
    require_episode(episode_id)
    with store.connect() as db:
        first = db.execute("SELECT id FROM users ORDER BY rowid LIMIT 1").fetchone()
        if not first or first[0] != store.current_user.get():
            raise HTTPException(403, "Only the first local account can import pre-account reports.")
        rows = db.execute("SELECT * FROM reports WHERE id NOT IN (SELECT report_id FROM report_access)").fetchall()
        for row in rows:
            payload = json.loads(row["payload"])
            payload["episode_id"] = episode_id
            db.execute("UPDATE reports SET payload=? WHERE id=?", (json.dumps(payload), row["id"]))
            db.execute("INSERT INTO report_access VALUES (?,?,?)", (row["id"], store.current_user.get(), episode_id))
    return workspace()


@router.post("/patients/{patient_id}/invitations", status_code=201)
def invite(patient_id: str, body: Invitation):
    require_patient(patient_id)
    now = datetime.now(timezone.utc)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        recipient = db.execute("SELECT id,username FROM users WHERE username=?", (body.username.lower(),)).fetchone()
        if not recipient:
            raise HTTPException(404, "Ask this person to create a local account, then enter their exact username.")
        if recipient["id"] == store.current_user.get():
            raise HTTPException(422, "You already own this patient profile.")
        db.execute("UPDATE caregiver_access SET status='expired',updated_at=? WHERE status='pending' AND expires_at<=?", (now.isoformat(), now.isoformat()))
        existing = db.execute("SELECT id FROM caregiver_access WHERE patient_id=? AND recipient_id=? AND status IN ('pending','active')", (patient_id, recipient["id"])).fetchone()
        if existing:
            raise HTTPException(409, "This person already has access or a pending invitation. Revoke it before inviting them with different permissions.")
        invitation_id = uuid4().hex
        db.execute("INSERT INTO caregiver_access VALUES (?,?,?,?,?,?,?,?)", (
            invitation_id, patient_id, recipient["id"], body.role, "pending", now.isoformat(),
            (now + timedelta(days=7)).isoformat(), now.isoformat()))
        store.audit(db, patient_id, "invited", invitation_id, f"{recipient['username']} / {body.role}")
        db.execute("INSERT INTO caregiver_alerts VALUES (?,?,?,?,?)", (invitation_id, body.taken, body.skipped, body.unconfirmed, body.delay_minutes))
    return workspace()


@router.put("/patients/{patient_id}/invitations/{invitation_id}/alerts")
def update_alerts(patient_id: str, invitation_id: str, change: AlertPreferences):
    require_patient(patient_id)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if not db.execute("SELECT 1 FROM caregiver_access WHERE id=? AND patient_id=? AND status IN ('pending','active')", (invitation_id, patient_id)).fetchone():
            raise HTTPException(404, "Active invitation not found.")
        db.execute("INSERT INTO caregiver_alerts VALUES (?,?,?,?,?) ON CONFLICT(grant_id) DO UPDATE SET taken=excluded.taken,skipped=excluded.skipped,unconfirmed=excluded.unconfirmed,delay_minutes=excluded.delay_minutes",
                   (invitation_id, change.taken, change.skipped, change.unconfirmed, change.delay_minutes))
        store.audit(db, patient_id, "caregiver_alerts_changed", invitation_id, change.model_dump_json())
    return workspace()


@router.get("/notifications")
def notifications():
    with store.connect() as db:
        return [dict(row) for row in db.execute("""SELECT care_notifications.*,patients.name AS patient_name FROM care_notifications
            JOIN caregiver_access ON caregiver_access.id=grant_id JOIN patients ON patients.id=care_notifications.patient_id
            WHERE user_id=? AND recipient_id=user_id AND caregiver_access.status='active'
            AND NOT EXISTS (SELECT 1 FROM report_archives WHERE report_id=care_notifications.report_id)
            AND EXISTS (SELECT 1 FROM reports WHERE id=care_notifications.report_id)
            ORDER BY care_notifications.created_at DESC LIMIT 100""", (store.current_user.get(),))]


@router.post("/notifications/{notification_id}/read")
def read_notification(notification_id: str):
    with store.connect() as db:
        row = db.execute("""SELECT care_notifications.id FROM care_notifications JOIN caregiver_access ON caregiver_access.id=grant_id
            WHERE care_notifications.id=? AND user_id=? AND caregiver_access.status='active' AND recipient_id=user_id""", (notification_id, store.current_user.get())).fetchone()
        if not row:
            raise HTTPException(404, "Update not found.")
        db.execute("UPDATE care_notifications SET read_at=? WHERE id=?", (datetime.now(timezone.utc).isoformat(), notification_id))
    return {"ok": True}


def notify_caregivers(db, patient_id, schedule, due_at, kind, now=None):
    now = now or datetime.now(timezone.utc)
    patient = db.execute("SELECT name FROM patients WHERE id=?", (patient_id,)).fetchone()
    if kind in {"taken", "skipped", "undo"}:
        db.execute("UPDATE care_notifications SET read_at=? WHERE schedule_id=? AND due_at=? AND read_at IS NULL", (now.isoformat(), schedule["id"], due_at))
    for grant in db.execute("""SELECT caregiver_access.*,caregiver_alerts.taken,caregiver_alerts.skipped,
        caregiver_alerts.unconfirmed,caregiver_alerts.delay_minutes FROM caregiver_access
        JOIN caregiver_alerts ON grant_id=caregiver_access.id WHERE patient_id=? AND status='active'""", (patient_id,)).fetchall():
        if kind == "undo":
            previously_notified = db.execute("SELECT 1 FROM care_notifications WHERE grant_id=? AND schedule_id=? AND due_at=? AND kind IN ('taken','skipped')", (grant["id"], schedule["id"], due_at)).fetchone()
            if not previously_notified:
                continue
            message = "The dose record was undone; it is currently unconfirmed."
        elif kind == "unconfirmed":
            if datetime.fromisoformat(due_at) < datetime.fromisoformat(grant["updated_at"]) or datetime.fromisoformat(due_at) < datetime.fromisoformat(schedule["created_at"]):
                continue
            if not grant["unconfirmed"] or now < datetime.fromisoformat(due_at) + timedelta(minutes=grant["delay_minutes"]):
                continue
            message = f"No confirmation received {grant['delay_minutes']} minutes after the scheduled time. This does not prove a missed dose."
        else:
            if not grant[kind]:
                continue
            message = f"The dose was marked {kind}. This is a recorded update, not proof of ingestion."
        event = f"{grant['id']}:{schedule['id']}:{due_at}:{kind}"
        if kind != "unconfirmed":
            event += ":" + now.isoformat()
        body = f"{patient['name']} · {schedule['payload']['name']}: {message}"
        db.execute("INSERT OR IGNORE INTO care_notifications VALUES (?,?,?,?,?,?,?,?,?,?,?,NULL)",
                   (uuid4().hex, grant["id"], grant["recipient_id"], patient_id, schedule["report_id"], schedule["id"], due_at, kind, body, event, now.isoformat()))


@router.post("/invitations/{invitation_id}/respond")
def respond(invitation_id: str, body: InvitationResponse):
    now = datetime.now(timezone.utc).isoformat()
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        invitation = db.execute("SELECT * FROM caregiver_access WHERE id=? AND recipient_id=?", (invitation_id, store.current_user.get())).fetchone()
        if not invitation:
            raise HTTPException(404, "Invitation not found.")
        if invitation["status"] != "pending" or invitation["expires_at"] <= now:
            raise HTTPException(409, "This invitation is no longer available. Ask the owner for a new invitation.")
        db.execute("UPDATE caregiver_access SET status=?,updated_at=? WHERE id=?", ("active" if body.action == "accept" else "declined", now, invitation_id))
        store.audit(db, invitation["patient_id"], "accepted" if body.action == "accept" else "declined", invitation_id, invitation["role"])
    return workspace()


@router.post("/patients/{patient_id}/invitations/{invitation_id}/revoke")
def revoke(patient_id: str, invitation_id: str):
    require_patient(patient_id)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        invitation = db.execute("SELECT * FROM caregiver_access WHERE id=? AND patient_id=?", (invitation_id, patient_id)).fetchone()
        if not invitation:
            raise HTTPException(404, "Invitation not found.")
        if invitation["status"] in {"active", "pending"}:
            db.execute("UPDATE caregiver_access SET status='revoked',updated_at=? WHERE id=?", (datetime.now(timezone.utc).isoformat(), invitation_id))
            store.audit(db, patient_id, "revoked", invitation_id, invitation["role"])
    return workspace()


@router.get("/patients/{patient_id}/access-history")
def access_history(patient_id: str):
    require_patient(patient_id)
    with store.connect() as db:
        return [dict(row) for row in db.execute("""SELECT care_audit.*, actor.username AS actor_name,
            recipient.username AS recipient_name FROM care_audit JOIN users AS actor ON actor.id=actor_id
            LEFT JOIN caregiver_access ON caregiver_access.id=target_id
            LEFT JOIN users AS recipient ON recipient.id=caregiver_access.recipient_id
            WHERE care_audit.patient_id=? ORDER BY care_audit.id DESC LIMIT 100""", (patient_id,))]
