import asyncio
import base64
import json
import logging
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import store
from .schedules import doses, now_utc, read_schedule

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)


def vapid_key():
    path = store.DATA / ".push-key"
    if not path.exists():
        private = ec.generate_private_key(ec.SECP256R1())
        from .vault import write_private
        write_private(path, private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    from .vault import read_private
    return serialization.load_pem_private_key(read_private(path), password=None)


def public_key():
    content = vapid_key().public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(content).rstrip(b"=").decode()


def current_reminders(db, user_id):
    result = []
    now = now_utc()
    for row in db.execute("""SELECT schedules.*,episodes.patient_id FROM schedules JOIN report_access ON schedules.report_id=report_access.report_id
        JOIN episodes ON report_access.episode_id=episodes.id WHERE schedules.status IN ('approved','active')""").fetchall():
        token = store.current_user.set(user_id)
        try:
            if store.patient_role(row["patient_id"], db) != "owner":
                continue
            schedule = read_schedule(db, row)
            if schedule["status"] not in {"approved", "active"}:
                continue
            for dose in doses(db, schedule):
                if dose["status"] != "pending":
                    continue
                alert = dose["snoozed_until"] or dose["due_at"]
                result.append({"schedule_id": schedule["id"], "report_id": schedule["report_id"],
                               "name": schedule["payload"]["name"], "dose": schedule["payload"]["dose"],
                               "due_at": dose["due_at"], "alert_at": alert,
                               "kind": "dose", "demo": schedule.get("authority") != "personal",
                               "alerting": now - timedelta(minutes=30) <= datetime.fromisoformat(alert) <= now})
        finally:
            store.current_user.reset(token)
    for row in db.execute("""SELECT care_notifications.* FROM care_notifications JOIN caregiver_access ON caregiver_access.id=grant_id
        WHERE user_id=? AND recipient_id=user_id AND caregiver_access.status='active' AND read_at IS NULL
        AND EXISTS (SELECT 1 FROM caregiver_alerts WHERE grant_id=caregiver_access.id AND
            (care_notifications.kind='undo' OR (care_notifications.kind='taken' AND taken=1) OR
             (care_notifications.kind='skipped' AND skipped=1) OR (care_notifications.kind='unconfirmed' AND unconfirmed=1)))
        AND EXISTS (SELECT 1 FROM reports WHERE id=care_notifications.report_id)
        AND NOT EXISTS (SELECT 1 FROM report_archives WHERE report_id=care_notifications.report_id)""", (user_id,)):
        created = datetime.fromisoformat(row["created_at"])
        result.append({"schedule_id": "care:" + row["id"], "report_id": row["report_id"], "name": "Care circle update",
                       "dose": "", "due_at": row["created_at"], "alert_at": row["created_at"], "demo": False,
                       "kind": "care", "notification_id": row["id"], "alerting": now - timedelta(hours=24) <= created <= now})
    return sorted(result, key=lambda item: item["due_at"])


@router.get("/reminders")
def reminders():
    with store.connect() as db:
        return current_reminders(db, store.current_user.get())


@router.get("/push/settings")
def settings():
    subject = os.environ.get("AFTERCARE_PUSH_SUBJECT", "")
    return {"configured": subject.startswith(("mailto:", "https://")), "public_key": public_key() if subject else None}


class Subscription(BaseModel):
    endpoint: str = Field(max_length=2000)
    keys: dict[str, str]


def validate_subscription(body):
    try:
        parsed = urlsplit(body.endpoint)
        port = parsed.port
    except ValueError:
        raise HTTPException(422, "Invalid push endpoint.")
    allowed = {"fcm.googleapis.com", "updates.push.services.mozilla.com", "updates-autopush.stage.mozaws.net", "web.push.apple.com"}
    host = parsed.hostname or ""
    if parsed.scheme != "https" or port not in {None, 443} or parsed.username or parsed.password or parsed.fragment or not parsed.path or not (host in allowed or host.endswith(".notify.windows.com")):
        raise HTTPException(422, "Use a subscription from a supported browser push provider.")
    try:
        auth = base64.urlsafe_b64decode(body.keys["auth"] + "==")
        key = base64.urlsafe_b64decode(body.keys["p256dh"] + "==")
        if len(auth) != 16:
            raise ValueError()
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), key)
    except (KeyError, ValueError):
        raise HTTPException(422, "Invalid browser push keys.")


@router.post("/push/devices")
def subscribe(body: Subscription):
    if not settings()["configured"]:
        raise HTTPException(409, "The installation administrator must configure the Web Push contact first.")
    validate_subscription(body)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        previous = db.execute("SELECT id,user_id FROM push_devices WHERE endpoint=?", (body.endpoint,)).fetchone()
        if previous and previous["user_id"] != store.current_user.get():
            db.execute("DELETE FROM push_deliveries WHERE device_id=?", (previous["id"],))
            db.execute("DELETE FROM push_devices WHERE id=?", (previous["id"],))
            previous = None
        identity = previous["id"] if previous else uuid4().hex
        db.execute("INSERT INTO push_devices VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET subscription=excluded.subscription",
                   (identity, store.current_user.get(), body.model_dump_json(), body.endpoint, now_utc().isoformat()))
    return {"id": identity}


@router.delete("/push/devices/{identity}")
def unsubscribe(identity: str):
    with store.connect() as db:
        row = db.execute("SELECT id FROM push_devices WHERE id=? AND user_id=?", (identity, store.current_user.get())).fetchone()
        if row:
            db.execute("DELETE FROM push_deliveries WHERE device_id=?", (identity,))
            db.execute("DELETE FROM push_devices WHERE id=?", (identity,))
    return {"ok": True}


def send_push(subscription, tag):
    from pywebpush import webpush
    private = vapid_key().private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption())
    import requests
    session = requests.Session()
    session.max_redirects = 0
    webpush(subscription_info=subscription, requests_session=session, data=json.dumps({"tag": tag}),
            vapid_private_key=base64.urlsafe_b64encode(private).decode(),
            vapid_claims={"sub": os.environ["AFTERCARE_PUSH_SUBJECT"]}, ttl=60, timeout=10)


def collect_unconfirmed():
    from .care import notify_caregivers
    with store.connect() as db:
        now = now_utc()
        for row in db.execute("SELECT schedules.*,episodes.patient_id FROM schedules JOIN report_access ON report_access.report_id=schedules.report_id JOIN episodes ON episodes.id=report_access.episode_id WHERE status IN ('active','approved')").fetchall():
            schedule = read_schedule(db, row)
            if schedule["status"] not in {"active", "approved"}:
                continue
            today = now.astimezone(ZoneInfo(schedule["payload"]["timezone"])).date()
            for day in (today - timedelta(days=1), today):
                for dose in doses(db, schedule, day):
                    due = datetime.fromisoformat(dose["due_at"])
                    if dose["status"] == "pending" and now - timedelta(hours=24) <= due <= now:
                        notify_caregivers(db, row["patient_id"], schedule, dose["due_at"], "unconfirmed", now)


def deliver_pending():
    collect_unconfirmed()
    if not os.environ.get("AFTERCARE_PUSH_SUBJECT"):
        return
    # One server process owns the installation. Persist attempts before network I/O.
    with store.connect() as db:
        devices = [dict(row) for row in db.execute("SELECT * FROM push_devices")]
    for device in devices:
        with store.connect() as db:
            candidates = current_reminders(db, device["user_id"])
        for item in candidates:
            if not item["alerting"]:
                continue
            key = (device["id"], item["schedule_id"], item["due_at"], item["alert_at"])
            with store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                # Recheck consent, credentials, source and recipient access at dispatch time.
                latest = current_reminders(db, device["user_id"])
                if not any(i["schedule_id"] == item["schedule_id"] and i["alert_at"] == item["alert_at"] and i["alerting"] for i in latest):
                    continue
                if not db.execute("SELECT 1 FROM push_devices WHERE id=? AND user_id=?", (device["id"], device["user_id"])).fetchone():
                    continue
                delivery = db.execute("SELECT * FROM push_deliveries WHERE device_id=? AND schedule_id=? AND due_at=? AND alert_at=?", key).fetchone()
                if delivery and (delivery["status"] == "sent" or delivery["attempts"] >= 3):
                    continue
                db.execute("INSERT INTO push_deliveries VALUES (?,?,?,?,'sending',1,?) ON CONFLICT(device_id,schedule_id,due_at,alert_at) DO UPDATE SET status='sending',attempts=attempts+1,updated_at=excluded.updated_at", (*key, now_utc().isoformat()))
            try:
                send_push(json.loads(device["subscription"]), item["schedule_id"] + ":" + item["due_at"])
                status = "sent"
            except Exception as error:
                status = "failed"
                response = getattr(error, "response", None)
                if response is not None and response.status_code in {404, 410}:
                    with store.connect() as db:
                        db.execute("DELETE FROM push_devices WHERE id=?", (device["id"],))
                logger.warning("Web Push delivery failed (%s).", type(error).__name__)
            with store.connect() as db:
                db.execute("UPDATE push_deliveries SET status=?,updated_at=? WHERE device_id=? AND schedule_id=? AND due_at=? AND alert_at=?", (status, now_utc().isoformat(), *key))


async def worker(stop):
    while not stop.is_set():
        try:
            await asyncio.to_thread(deliver_pending)
        except Exception:
            logger.exception("Reminder worker failed; it will retry on the next tick.")
        try:
            await asyncio.wait_for(stop.wait(), timeout=30)
        except TimeoutError:
            pass
