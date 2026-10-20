import json
import os
import sqlite3
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from fastapi import HTTPException

from . import vault

DATA = Path(os.environ.get("AFTERCARE_DATA", Path(__file__).resolve().parents[1] / "data"))
DATA.mkdir(parents=True, exist_ok=True)
current_user = ContextVar("current_user", default=None)


@contextmanager
def connect():
    with vault.DATABASE_LOCK:
        with database_connection() as connection:
            yield connection


@contextmanager
def database_connection():
    path = DATA / "aftercare.db"
    sealed = vault.enabled(DATA)
    connection = sqlite3.connect(":memory:" if sealed else path)
    existed = path.exists()
    if sealed and existed:
        connection.deserialize(vault.read(path))
    schema_before = connection.execute("PRAGMA schema_version").fetchone()[0]
    connection.row_factory = sqlite3.Row
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS personal_spaces (user_id TEXT PRIMARY KEY, patient_id TEXT NOT NULL, episode_id TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS routines (user_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS app_migrations (name TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS caregiver_alerts (
            grant_id TEXT PRIMARY KEY, taken INTEGER NOT NULL, skipped INTEGER NOT NULL,
            unconfirmed INTEGER NOT NULL, delay_minutes INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS care_notifications (
            id TEXT PRIMARY KEY, grant_id TEXT NOT NULL, user_id TEXT NOT NULL, patient_id TEXT NOT NULL,
            report_id TEXT NOT NULL, schedule_id TEXT NOT NULL, due_at TEXT NOT NULL, kind TEXT NOT NULL,
            body TEXT NOT NULL, event_key TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL, read_at TEXT
        );
        CREATE TABLE IF NOT EXISTS clinicians (
            user_id TEXT PRIMARY KEY, display_name TEXT NOT NULL, registration TEXT NOT NULL,
            verified_by TEXT NOT NULL, evidence TEXT NOT NULL, valid_until TEXT NOT NULL,
            active INTEGER NOT NULL, demo INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS schedules (
            id TEXT PRIMARY KEY, report_id TEXT NOT NULL, medication_group TEXT NOT NULL,
            owner_id TEXT NOT NULL, clinician_id TEXT NOT NULL, payload TEXT NOT NULL,
            fingerprint TEXT NOT NULL, status TEXT NOT NULL, consent INTEGER NOT NULL,
            created_at TEXT NOT NULL, reason TEXT NOT NULL, decision_at TEXT, decision_note TEXT
        );
        CREATE TABLE IF NOT EXISTS scheduled_doses (
            schedule_id TEXT NOT NULL, due_at TEXT NOT NULL, status TEXT NOT NULL,
            note TEXT NOT NULL, actor_id TEXT NOT NULL, recorded_at TEXT NOT NULL,
            snoozed_until TEXT, snapshot TEXT NOT NULL, PRIMARY KEY(schedule_id,due_at)
        );
        CREATE TABLE IF NOT EXISTS push_devices (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, subscription TEXT NOT NULL,
            endpoint TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS push_deliveries (
            device_id TEXT NOT NULL, schedule_id TEXT NOT NULL, due_at TEXT NOT NULL,
            alert_at TEXT NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL,
            updated_at TEXT NOT NULL, PRIMARY KEY(device_id,schedule_id,due_at,alert_at)
        );
        CREATE TABLE IF NOT EXISTS reports (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS recovery_codes (
            user_id TEXT PRIMARY KEY, code_hash TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS login_attempts (key TEXT NOT NULL, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS patients (
            id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, name TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS episodes (
            id TEXT PRIMARY KEY, patient_id TEXT NOT NULL, title TEXT NOT NULL, started TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS contacts (
            id TEXT PRIMARY KEY, patient_id TEXT NOT NULL, name TEXT NOT NULL,
            role TEXT NOT NULL, phone TEXT NOT NULL, note TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS report_access (
            report_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, episode_id TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS report_archives (
            report_id TEXT PRIMARY KEY, archived_at TEXT NOT NULL, archived_by TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS caregiver_access (
            id TEXT PRIMARY KEY, patient_id TEXT NOT NULL, recipient_id TEXT NOT NULL,
            role TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS one_open_invitation
            ON caregiver_access(patient_id,recipient_id) WHERE status IN ('pending','active');
        CREATE TABLE IF NOT EXISTS care_audit (
            id INTEGER PRIMARY KEY, patient_id TEXT NOT NULL, actor_id TEXT NOT NULL,
            action TEXT NOT NULL, target_id TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY, report_id TEXT NOT NULL, field_id TEXT NOT NULL,
            before TEXT NOT NULL, after TEXT NOT NULL, created TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS medication_entries (
            id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL,
            report_id TEXT NOT NULL, medication_group TEXT NOT NULL,
            status TEXT NOT NULL, occurred_at TEXT NOT NULL, note TEXT NOT NULL,
            snapshot TEXT NOT NULL, created_at TEXT NOT NULL, voided_at TEXT
        );
        CREATE TABLE IF NOT EXISTS visits (
            report_id TEXT NOT NULL, field_id TEXT NOT NULL,
            status TEXT NOT NULL, planned_date TEXT, note TEXT NOT NULL,
            source_value TEXT NOT NULL, updated_at TEXT NOT NULL,
            PRIMARY KEY (report_id, field_id)
        );
    """)
    for table, column in [("schedules", "authority"), ("medication_entries", "actor_id"), ("medication_entries", "voided_by"), ("visits", "actor_id")]:
        if column not in {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT" + (" DEFAULT 'clinical'" if column == "authority" else ""))
    try:
        with connection:
            yield connection
        if sealed and (not existed or connection.total_changes or schema_before != connection.execute("PRAGMA schema_version").fetchone()[0]):
            vault.write(path, connection.serialize())
    finally:
        connection.close()


def save(report: dict, empty_only=False, expected=None):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute("SELECT payload FROM reports WHERE id=?", (report["id"],)).fetchone()
        if existing:
            require_report_permission(report["id"], "edit", db)
            if expected is not None and json.loads(existing["payload"]) != expected:
                raise HTTPException(409, "This report changed. Refresh before saving the plan.")
        if empty_only:
            if not existing or json.loads(existing["payload"])["fields"]:
                raise HTTPException(409, "This report changed while it was being read. Refresh to keep the existing details and review history.")
        if not existing:
            if not current_user.get() or not report.get("episode_id"):
                raise ValueError("A new report needs an owner and recovery episode.")
            db.execute("INSERT INTO report_access VALUES (?,?,?)",
                       (report["id"], current_user.get(), report["episode_id"]))
        db.execute("INSERT INTO reports VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                   (report["id"], json.dumps(report)))


def get(report_id: str, db=None) -> dict | None:
    if db is None:
        with connect() as connection:
            return get(report_id, connection)
    row = db.execute("""SELECT payload FROM reports JOIN report_access ON report_id=reports.id
        JOIN episodes ON episodes.id=episode_id JOIN patients ON patients.id=patient_id
        WHERE reports.id=? AND NOT EXISTS (SELECT 1 FROM report_archives WHERE report_id=reports.id)
        AND (patients.owner_id=? OR EXISTS (
            SELECT 1 FROM caregiver_access WHERE patient_id=patients.id AND recipient_id=? AND status='active'))""",
        (report_id, current_user.get(), current_user.get())).fetchone()
    if row:
        return json.loads(row[0])
    from .schedules import clinical_report
    return clinical_report(db, report_id)


def patient_role(patient_id: str, db):
    row = db.execute("""SELECT CASE WHEN owner_id=? THEN 'owner' ELSE (
        SELECT role FROM caregiver_access WHERE patient_id=patients.id AND recipient_id=? AND status='active') END AS role
        FROM patients WHERE id=?""", (current_user.get(), current_user.get(), patient_id)).fetchone()
    return row["role"] if row else None


def require_report_permission(report_id: str, action: str, db=None, include_archived=False):
    if db is None:
        with connect() as connection:
            return require_report_permission(report_id, action, connection, include_archived)
    if not include_archived and db.execute("SELECT 1 FROM report_archives WHERE report_id=?", (report_id,)).fetchone():
        raise HTTPException(404, "Report not found.")
    row = db.execute("SELECT patient_id FROM report_access JOIN episodes ON episode_id=episodes.id WHERE report_id=?", (report_id,)).fetchone()
    role = patient_role(row["patient_id"], db) if row else None
    if not role:
        raise HTTPException(404, "Report not found.")
    if role != "owner" and not (action == "record" and role == "recorder"):
        raise HTTPException(403, "Your access does not allow this change.")
    return row["patient_id"]


def audit(db, patient_id: str, action: str, target_id: str, detail=""):
    db.execute("INSERT INTO care_audit(patient_id,actor_id,action,target_id,detail,created_at) VALUES (?,?,?,?,?,?)",
               (patient_id, current_user.get(), action, target_id, detail, datetime.now(timezone.utc).isoformat()))


def all_reports() -> list[dict]:
    with connect() as db:
        return [json.loads(row[0]) for row in db.execute(
            """SELECT payload FROM reports JOIN report_access ON report_id=reports.id
            JOIN episodes ON episodes.id=episode_id JOIN patients ON patients.id=patient_id
            WHERE NOT EXISTS (SELECT 1 FROM report_archives WHERE report_id=reports.id)
                AND (patients.owner_id=? OR EXISTS (SELECT 1 FROM caregiver_access
                WHERE patient_id=patients.id AND recipient_id=? AND status='active')) ORDER BY reports.rowid DESC""",
            (current_user.get(), current_user.get()))]


def review(report: dict, field: dict, before: dict):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        require_report_permission(report["id"], "edit", db)
        current = get(report["id"], db)
        index = next((i for i, item in enumerate(current["fields"]) if item["id"] == field["id"]), None)
        if index is None or current["fields"][index] != before:
            raise HTTPException(409, "This field changed. Refresh before reviewing it again.")
        current["fields"][index] = field
        current["plan_saved"] = False
        from .schedules import suspend
        suspend(db, report["id"], "Source review changed. Request a new clinical review.")
        report.update(current)
        db.execute("UPDATE reports SET payload=? WHERE id=?", (json.dumps(report), report["id"]))
        db.execute("INSERT INTO reviews(report_id,field_id,before,after,created) VALUES (?,?,?,?,?)",
                   (report["id"], field["id"], json.dumps(before), json.dumps(field), datetime.now(timezone.utc).isoformat()))


def history(report_id: str) -> list[dict]:
    with connect() as db:
        return [dict(row) for row in db.execute("SELECT * FROM reviews WHERE report_id=? ORDER BY id DESC", (report_id,))]
