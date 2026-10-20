import io
import json
from datetime import datetime, timezone
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import store, vault

router = APIRouter(prefix="/api/reports")


class DeleteReport(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    name: str = Field(max_length=300)
    archive_first: bool = False


@router.delete("/{report_id}")
def delete_report(report_id: str, proof: DeleteReport, request: Request):
    from .auth import password_matches, throttle, clear_attempts
    attempt = throttle(request, "delete-report:" + store.current_user.get())
    tomb = None
    path = None
    try:
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            patient_id = store.require_report_permission(report_id, "manage", db, include_archived=True)
            if not proof.archive_first and not db.execute("SELECT 1 FROM report_archives WHERE report_id=?", (report_id,)).fetchone():
                raise HTTPException(409, "Archive the report before permanently deleting it.")
            report = json.loads(db.execute("SELECT payload FROM reports WHERE id=?", (report_id,)).fetchone()[0])
            user = db.execute("SELECT username,password FROM users WHERE id=?", (store.current_user.get(),)).fetchone()
            if proof.name != report["name"]:
                raise HTTPException(422, "Type the complete report name to confirm deletion.")
            if not password_matches(proof.current_password, user["password"]):
                raise HTTPException(403, "The current password is incorrect.")
            name = vault.source_name(report)
            if name is not None:
                path = store.DATA / name
                if path.resolve().parent != store.DATA.resolve() or path.is_symlink():
                    raise HTTPException(409, "The source path is unsafe.")
                tomb = path.with_name(".delete-" + path.name)
                if tomb.exists():
                    raise HTTPException(409, "A previous deletion needs installation recovery.")
                if path.exists():
                    path.replace(tomb)
            db.execute("DELETE FROM care_audit WHERE patient_id=? AND (target_id=? OR target_id IN (SELECT id FROM medication_entries WHERE report_id=?) OR target_id IN (SELECT field_id FROM visits WHERE report_id=?))", (patient_id, report_id, report_id, report_id))
            db.execute("DELETE FROM push_deliveries WHERE schedule_id IN (SELECT id FROM schedules WHERE report_id=?)", (report_id,))
            db.execute("DELETE FROM scheduled_doses WHERE schedule_id IN (SELECT id FROM schedules WHERE report_id=?)", (report_id,))
            for table in ("schedules", "reviews", "medication_entries", "visits", "report_archives", "report_access"):
                db.execute(f"DELETE FROM {table} WHERE report_id=?", (report_id,))
            db.execute("DELETE FROM care_notifications WHERE report_id=?", (report_id,))
            db.execute("DELETE FROM reports WHERE id=?", (report_id,))
            store.audit(db, patient_id, "report_permanently_deleted", report_id)
    except Exception:
        if tomb and path and tomb.exists():
            tomb.replace(path)
        raise
    if tomb:
        tomb.unlink(missing_ok=True)
    clear_attempts(attempt)
    return {"id": report_id, "deleted": True}


@router.get("/archived")
def archived_reports():
    with store.connect() as db:
        rows = db.execute("""SELECT reports.payload, archived_at FROM report_archives
            JOIN reports ON reports.id=report_id JOIN report_access USING(report_id)
            JOIN episodes ON episodes.id=episode_id JOIN patients ON patients.id=patient_id
            WHERE patients.owner_id=? ORDER BY archived_at DESC""", (store.current_user.get(),))
        archived = []
        for row in rows:
            report = json.loads(row["payload"])
            archived.append({"id": report["id"], "name": report["name"],
                             "episode_id": report["episode_id"], "archived_at": row["archived_at"]})
        return archived


@router.post("/{report_id}/archive")
def archive_report(report_id: str):
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        patient_id = store.require_report_permission(report_id, "manage", db, include_archived=True)
        from .schedules import suspend
        suspend(db, report_id, "The report was archived. A new approval is required after restoration.")
        result = db.execute("INSERT OR IGNORE INTO report_archives VALUES (?,?,?)",
                            (report_id, datetime.now(timezone.utc).isoformat(), store.current_user.get()))
        if result.rowcount:
            report = json.loads(db.execute("SELECT payload FROM reports WHERE id=?", (report_id,)).fetchone()[0])
            store.audit(db, patient_id, "report_archived", report_id, report["name"])
    return {"id": report_id}


@router.post("/{report_id}/restore")
def restore_report(report_id: str):
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        patient_id = store.require_report_permission(report_id, "manage", db, include_archived=True)
        result = db.execute("DELETE FROM report_archives WHERE report_id=?", (report_id,))
        report = store.get(report_id, db)
        if result.rowcount:
            store.audit(db, patient_id, "report_restored", report_id, report["name"])
        return report


@router.get("/{report_id}/export")
def export_report(report_id: str):
    with store.connect() as db:
        # One transaction keeps the source, reviews and care records in the same snapshot.
        db.execute("BEGIN IMMEDIATE")
        patient_id = store.require_report_permission(report_id, "manage", db)
        report = store.get(report_id, db)
        name = vault.source_name(report)
        original_name, source = None, None
        if name is not None:
            path = (store.DATA / name).resolve()
            if path.parent != store.DATA.resolve() or not path.is_file():
                raise HTTPException(409, "The original file is missing. Restore the local source file before exporting.")
            source = vault.read(path)
            extension = path.suffix.lower()
            if extension not in {".pdf", ".jpg", ".jpeg", ".png"}:
                raise HTTPException(409, "The original file format is not supported for export.")
            original_name = f"original{extension}"
        context = dict(db.execute("""SELECT patients.id AS patient_id, patients.name AS patient_name,
            episodes.id AS episode_id, title AS episode_title, started AS episode_started,
            users.username AS owner_username FROM patients JOIN episodes ON patient_id=patients.id
            JOIN users ON users.id=patients.owner_id WHERE episodes.id=?""", (report["episode_id"],)).fetchone())
        reviews = [dict(row) for row in db.execute("SELECT * FROM reviews WHERE report_id=? ORDER BY id", (report_id,))]
        for review in reviews:
            for key in ("before", "after"):
                review[key] = json.loads(review[key])
        medications = [dict(row) for row in db.execute("""SELECT medication_entries.*, actor.username AS actor_name,
            undoer.username AS voided_by_name FROM medication_entries LEFT JOIN users actor ON actor.id=actor_id
            LEFT JOIN users undoer ON undoer.id=voided_by WHERE report_id=? ORDER BY created_at,id""", (report_id,))]
        for medication in medications:
            medication["snapshot"] = json.loads(medication["snapshot"])
        visits = [dict(row) for row in db.execute("""SELECT visits.*, users.username AS actor_name
            FROM visits LEFT JOIN users ON users.id=actor_id WHERE report_id=? ORDER BY field_id""", (report_id,))]
        store.audit(db, patient_id, "report_exported", report_id, report["name"])
        audit = [dict(row) for row in db.execute("""SELECT care_audit.*,users.username AS actor_name
            FROM care_audit LEFT JOIN users ON users.id=actor_id WHERE patient_id=? AND
            (target_id=? OR target_id IN (SELECT id FROM medication_entries WHERE report_id=?)
            OR target_id IN (SELECT field_id FROM visits WHERE report_id=?)) ORDER BY care_audit.id""",
            (patient_id, report_id, report_id, report_id))]
        report.pop("file")
        schedules = [dict(row) for row in db.execute("SELECT * FROM schedules WHERE report_id=? ORDER BY created_at", (report_id,))]
        for schedule in schedules:
            schedule["payload"] = json.loads(schedule["payload"])
            schedule["dose_records"] = [dict(row) for row in db.execute("SELECT * FROM scheduled_doses WHERE schedule_id=? ORDER BY due_at", (schedule["id"],))]
        exported = {"format": "aftercare-report", "version": 2, "clinical_schedules": schedules,
                    "exported_at": datetime.now(timezone.utc).isoformat(), "context": context,
                    "original_file": original_name, "report": report, "reviews": reviews,
                    "medications": medications, "visits": visits, "audit": audit}
    output = io.BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as bundle:
        if original_name:
            bundle.writestr(original_name, source)
        bundle.writestr("report.json", json.dumps(exported, ensure_ascii=False, indent=2))
        bundle.writestr("README.txt", "AfterCare report export\n\n"
            "Includes an uploaded original and evidence when present. Manual medicine entries have no source document. Includes review before/after history, "
            "all medication records (including undone records), current visit details and related activity audit.\n"
            "Visit audit records identify changes but do not store every previous booking/note. "
            "Older records may have unknown authors.\n"
            "This is a portable copy of one report, not an account backup. Import/restore from ZIP is not supported. "
            "Patient contacts, access grants, credentials and sessions are not included.\n"
            "The ZIP is not encrypted. Keep downloaded copies private; archiving or revoking app access cannot recall them.\n"
            "Review confirms transcription only, not clinical appropriateness. This export does not activate reminders; personal reminder settings, historical decisions and dose records are included separately.\n")
    return Response(output.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="aftercare-report.zip"'})
