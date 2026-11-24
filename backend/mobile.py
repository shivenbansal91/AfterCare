from datetime import timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request

from . import store
from .auth import session_user
from .personal import personal_space
from .schedules import doses, list_schedules_in_transaction, now_utc
from .tracking import activity

router = APIRouter(prefix="/api/mobile")


@router.get("/snapshot")
def snapshot(request: Request):
    account = session_user(request)
    if not account:
        raise HTTPException(401, "Sign in to download your plans.")
    workspace = personal_space()
    # Shared records stay online so a caretaker cannot retain offline access after revocation.
    workspace["patients"] = [patient for patient in workspace["patients"] if patient["access_role"] == "owner"]
    workspace["invitations"] = []
    workspace["legacy_count"] = 0
    episodes = {episode["id"] for patient in workspace["patients"] for episode in patient["episodes"]}
    reports = [report for report in store.all_reports() if report["episode_id"] in episodes]
    schedules = {}
    activities = {}
    now = now_utc()
    with store.connect() as db:
        for report in reports:
            values = list_schedules_in_transaction(db, report["id"])
            for schedule in values:
                schedule["offline_doses"] = []
                if schedule["status"] not in {"active", "approved"}:
                    continue
                first = now.astimezone(ZoneInfo(schedule["payload"]["timezone"])).date()
                schedule["offline_doses"] = [dose for offset in range(8) for dose in doses(db, schedule, first + timedelta(days=offset))]
            schedules[report["id"]] = values
    for report in reports:
        activities[report["id"]] = activity(report["id"])
    return {"version": 1, "account": account, "workspace": workspace, "reports": reports,
            "schedules": schedules, "activities": activities, "synced_at": now.isoformat(),
            "valid_until": (now + timedelta(days=7)).isoformat()}
