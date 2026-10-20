import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator

from . import store
from .schedules import ScheduleDraft, doses, fingerprint, list_schedules_in_transaction, now_utc, read_schedule, suspend

router = APIRouter(prefix="/api")


class Routine(BaseModel):
    wake: str = "07:00"
    breakfast: str = "08:00"
    lunch: str = "13:00"
    dinner: str = "19:00"
    sleep: str = "23:00"
    timezone: str = "Asia/Kolkata"

    @model_validator(mode="after")
    def validate_times(self):
        for key in ("wake", "breakfast", "lunch", "dinner", "sleep"):
            if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", getattr(self, key)):
                raise ValueError("Use 24-hour times such as 07:30.")
        try:
            ZoneInfo(self.timezone)
        except (KeyError, ValueError):
            raise ValueError("Choose a valid time zone.")
        if self.wake == self.sleep:
            raise ValueError("Wake and sleep times must be different.")
        return self


class ReviewedField(BaseModel):
    id: str
    value: str = Field(max_length=2000)
    status: Literal["confirmed", "clarify", "rejected"]


class PlanReview(BaseModel):
    revision: str
    fields: list[ReviewedField] = Field(min_length=1, max_length=200)


class ManualField(BaseModel):
    group: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=2000)


class ManualMedicine(BaseModel):
    request_id: UUID
    name: str = Field(min_length=1, max_length=200)
    strength: str = Field(default="", max_length=200)
    dose: str = Field(min_length=1, max_length=200)
    frequency: str = Field(min_length=1, max_length=300)
    instructions: str = Field(default="", max_length=2000)
    duration: str = Field(default="", max_length=200)
    reason: str = Field(default="", max_length=1000)
    confirmed: Literal[True]


class ManualVisit(BaseModel):
    request_id: UUID
    title: str = Field(min_length=1, max_length=200)
    details: str = Field(default="", max_length=1000)
    planned_date: date | None = None
    note: str = Field(default="", max_length=500)
    confirmed: Literal[True]


class PersonalReminder(BaseModel):
    group: str = Field(min_length=1, max_length=100)
    dose: str = Field(min_length=1, max_length=200)
    times: list[str] = Field(min_length=1, max_length=8)
    start: date
    end: date
    timezone: str
    confirmed: Literal[True]
    revision: str

    @model_validator(mode="after")
    def validate_dates(self):
        ScheduleDraft(**self.model_dump(exclude={"confirmed", "revision"}), clinician_id="unused", consent=True)
        self.times.sort()
        return self


def migrate_personal_mode():
    with store.connect() as db:
        if not db.execute("SELECT 1 FROM app_migrations WHERE name='personal-reminders-v1'").fetchone():
            db.execute("UPDATE schedules SET status='suspended',consent=0,reason='Review these details and confirm your personal reminder times.' WHERE authority='clinical' AND status IN ('requested','approved')")
            db.execute("INSERT INTO app_migrations VALUES ('personal-reminders-v1')")


@router.post("/care/personal")
def personal_space():
    from .care import workspace
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        identity = store.current_user.get()
        if not db.execute("SELECT 1 FROM personal_spaces WHERE user_id=?", (identity,)).fetchone():
            patient = db.execute("SELECT id FROM patients WHERE owner_id=? ORDER BY rowid LIMIT 1", (identity,)).fetchone()
            patient_id = patient[0] if patient else uuid4().hex
            if not patient:
                db.execute("INSERT INTO patients VALUES (?,?,?)", (patient_id, identity, "Me"))
            episode = db.execute("SELECT id FROM episodes WHERE patient_id=? ORDER BY started DESC,rowid DESC LIMIT 1", (patient_id,)).fetchone()
            episode_id = episode[0] if episode else uuid4().hex
            if not episode:
                db.execute("INSERT INTO episodes VALUES (?,?,?,?)", (episode_id, patient_id, "My prescriptions", now_utc().date().isoformat()))
            db.execute("INSERT INTO personal_spaces VALUES (?,?,?)", (identity, patient_id, episode_id))
    result = workspace()
    with store.connect() as db:
        result["personal"] = dict(db.execute("SELECT patient_id,episode_id FROM personal_spaces WHERE user_id=?", (store.current_user.get(),)).fetchone())
    return result


@router.get("/care/routine")
def get_routine():
    with store.connect() as db:
        row = db.execute("SELECT payload FROM routines WHERE user_id=?", (store.current_user.get(),)).fetchone()
    return json.loads(row[0]) if row else Routine().model_dump()


@router.put("/care/routine")
def save_routine(body: Routine):
    with store.connect() as db:
        db.execute("INSERT INTO routines VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET payload=excluded.payload", (store.current_user.get(), body.model_dump_json()))
    return body


@router.get("/care/today")
def today_doses(patient_id: str):
    with store.connect() as db:
        if not store.patient_role(patient_id, db):
            raise HTTPException(404, "Care records not found.")
        result = []
        rows = db.execute("""SELECT schedules.* FROM schedules JOIN report_access ON report_access.report_id=schedules.report_id
            JOIN episodes ON episodes.id=report_access.episode_id WHERE patient_id=? AND status IN ('active','approved')""", (patient_id,)).fetchall()
        for row in rows:
            schedule = read_schedule(db, row)
            if schedule["status"] not in {"active", "approved"}:
                continue
            for dose in doses(db, schedule):
                result.append({**dose, "schedule_id": schedule["id"], "report_id": schedule["report_id"],
                               "name": schedule["payload"]["name"], "strength": schedule["payload"].get("strength", ""), "dose": schedule["payload"]["dose"],
                               "timezone": schedule["payload"]["timezone"]})
        return sorted(result, key=lambda dose: dose["due_at"])


def review_state(report, db):
    return {**report, "revision": fingerprint(report, db)}


@router.post("/medicines/manual", status_code=201)
def add_manual_medicine(body: ManualMedicine, episode_id: str | None = None):
    from .care import require_episode
    episode_id = require_episode(episode_id or personal_space()["personal"]["episode_id"])["id"]
    values = {"Name": body.name.strip(), "Strength": body.strength.strip(), "Dose": body.dose.strip(),
              "Frequency": body.frequency.strip(), "Instructions": body.instructions.strip(),
              "Duration": body.duration.strip(), "Indication": body.reason.strip()}
    if any(not values[key] for key in ("Name", "Dose", "Frequency")):
        raise HTTPException(422, "Enter the medicine name, dose and frequency or exact times.")
    identity = "manual-" + body.request_id.hex
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        previous = db.execute("SELECT payload FROM reports WHERE id=?", (identity,)).fetchone()
        if previous:
            store.require_report_permission(identity, "edit", db)
            report = store.get(identity, db)
            if report["episode_id"] != episode_id or {f["label"]: f["value"] for f in report["fields"]} != {key: value for key, value in values.items() if value}:
                raise HTTPException(409, "This medicine was already saved with different details. Open it to edit.")
            return review_state(report, db)
        fields = [{"id": uuid4().hex, "group": "Medication 1", "label": label, "value": value,
                   "status": "confirmed", "source": None, "origin": "manual"} for label, value in values.items() if value]
        created = now_utc().isoformat()
        report = {"id": identity, "kind": "manual", "name": values["Name"] + " — added by you", "file": None,
                  "engine": "manual", "sample": False, "episode_id": episode_id, "created": created,
                  "pages": [], "fields": fields, "plan_saved": True, "warnings": ["Added by you. No prescription was uploaded."]}
        db.execute("INSERT INTO reports VALUES (?,?)", (identity, json.dumps(report)))
        db.execute("INSERT INTO report_access VALUES (?,?,?)", (identity, store.current_user.get(), episode_id))
        for field in fields:
            db.execute("INSERT INTO reviews(report_id,field_id,before,after,created) VALUES (?,?,?,?,?)", (identity, field["id"], "null", json.dumps(field), created))
        patient_id = db.execute("SELECT patient_id FROM episodes WHERE id=?", (episode_id,)).fetchone()[0]
        store.audit(db, patient_id, "manual_medicine_added", identity)
        return review_state(report, db)


@router.post("/visits/manual", status_code=201)
def add_manual_visit(body: ManualVisit, episode_id: str | None = None):
    from .care import require_episode
    episode_id = require_episode(episode_id or personal_space()["personal"]["episode_id"])["id"]
    title, details, note = body.title.strip(), body.details.strip(), body.note.strip()
    if not title:
        raise HTTPException(422, "Enter a visit title.")
    value = title + (" — " + details if details else "")
    planned = body.planned_date.isoformat() if body.planned_date else None
    identity = "manual-visit-" + body.request_id.hex
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        previous = db.execute("SELECT payload FROM reports WHERE id=?", (identity,)).fetchone()
        if previous:
            store.require_report_permission(identity, "edit", db)
            report = store.get(identity, db)
            visit = db.execute("SELECT planned_date,note FROM visits WHERE report_id=?", (identity,)).fetchone()
            if report["episode_id"] != episode_id or report["fields"][0]["value"] != value or not visit or (visit["planned_date"], visit["note"]) != (planned, note):
                raise HTTPException(409, "This visit was already saved with different details. Open it to edit.")
            return review_state(report, db)
        created = now_utc().isoformat()
        field = {"id": uuid4().hex, "group": "Visits", "label": "Appointment", "value": value,
                 "status": "confirmed", "source": None, "origin": "manual"}
        report = {"id": identity, "kind": "manual", "entry_type": "visit", "name": title + " — visit added by you", "file": None,
                  "engine": "manual", "sample": False, "episode_id": episode_id, "created": created,
                  "pages": [], "fields": [field], "plan_saved": True, "warnings": ["Visit added by you. No document was uploaded."]}
        db.execute("INSERT INTO reports VALUES (?,?)", (identity, json.dumps(report)))
        db.execute("INSERT INTO report_access VALUES (?,?,?)", (identity, store.current_user.get(), episode_id))
        db.execute("INSERT INTO reviews(report_id,field_id,before,after,created) VALUES (?,?,?,?,?)", (identity, field["id"], "null", json.dumps(field), created))
        db.execute("INSERT INTO visits (report_id,field_id,status,planned_date,note,source_value,updated_at,actor_id) VALUES (?,?,?,?,?,?,?,?)",
                   (identity, field["id"], "booked" if planned else "planned", planned, note, value, created, store.current_user.get()))
        patient_id = db.execute("SELECT patient_id FROM episodes WHERE id=?", (episode_id,)).fetchone()[0]
        store.audit(db, patient_id, "manual_visit_added", identity)
        return review_state(report, db)


@router.get("/care/visits")
def patient_visits(patient_id: str):
    with store.connect() as db:
        if not store.patient_role(patient_id, db):
            raise HTTPException(404, "Care records not found.")
        rows = db.execute("""SELECT reports.payload FROM reports JOIN report_access ON reports.id=report_access.report_id
            JOIN episodes ON report_access.episode_id=episodes.id WHERE episodes.patient_id=?
            AND NOT EXISTS (SELECT 1 FROM report_archives WHERE report_id=reports.id) ORDER BY reports.rowid DESC""", (patient_id,)).fetchall()
        result = []
        for row in rows:
            report = json.loads(row["payload"])
            visits = {item["field_id"]: dict(item) for item in db.execute("""SELECT visits.*,users.username AS actor_name FROM visits
                LEFT JOIN users ON users.id=actor_id WHERE report_id=?""", (report["id"],))}
            for field in report["fields"]:
                if field["group"] == "Visits" and field["status"] != "rejected":
                    result.append({"report_id": report["id"], "report_name": report["name"], "plan_saved": report["plan_saved"],
                                   "field": field, "visit": visits.get(field["id"])})
        return result


@router.get("/reports/{report_id}/overview")
def overview(report_id: str):
    with store.connect() as db:
        report = store.get(report_id, db)
        if not report:
            raise HTTPException(404, "Report not found.")
        return review_state(report, db)


@router.put("/reports/{report_id}/review")
def confirm_overview(report_id: str, change: PlanReview):
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        patient_id = store.require_report_permission(report_id, "edit", db)
        report = store.get(report_id, db)
        if change.revision != fingerprint(report, db):
            raise HTTPException(409, "This report changed. Refresh the overview before confirming.")
        incoming = {field.id: field for field in change.fields}
        if len(incoming) != len(change.fields) or set(incoming) != {field["id"] for field in report["fields"]}:
            raise HTTPException(409, "Confirm the complete current overview, including excluded details.")
        changed = False
        for field in report["fields"]:
            replacement = incoming[field["id"]]
            if replacement.status == "confirmed" and not replacement.value.strip():
                raise HTTPException(422, "Fill in empty details or mark them as missing/excluded.")
            before = dict(field)
            field.update(value=replacement.value.strip(), status=replacement.status)
            if before != field:
                changed = True
                db.execute("INSERT INTO reviews(report_id,field_id,before,after,created) VALUES (?,?,?,?,?)", (report_id, field["id"], json.dumps(before), json.dumps(field), now_utc().isoformat()))
        if not any(field["status"] == "confirmed" for field in report["fields"]):
            raise HTTPException(422, "Confirm at least one non-empty detail.")
        if changed:
            suspend(db, report_id, "Prescription details changed. Reconfirm reminder times.")
        report["plan_saved"] = True
        db.execute("UPDATE reports SET payload=? WHERE id=?", (json.dumps(report), report_id))
        store.audit(db, patient_id, "overview_confirmed", report_id)
        return review_state(report, db)


@router.post("/reports/{report_id}/fields", status_code=201)
def add_field(report_id: str, change: ManualField):
    group, label, value = change.group.strip(), change.label.strip(), change.value.strip()
    if not value or not label or not (re.fullmatch(r"Medication [1-9]\d?", group) or group in {"Patient", "Contacts", "Care team", "Recovery", "Visits"}):
        raise HTTPException(422, "Choose a supported section and enter a label and value.")
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        store.require_report_permission(report_id, "edit", db)
        report = store.get(report_id, db)
        if len(report["fields"]) >= 200:
            raise HTTPException(422, "This report has reached its detail limit.")
        if any(field["group"] == group and field["label"].casefold() == label.casefold() for field in report["fields"]):
            raise HTTPException(409, "Edit the existing detail instead of adding a duplicate.")
        field = {"id": uuid4().hex, "group": group, "label": label, "value": value, "status": "pending", "source": None, "origin": "manual"}
        report["fields"].append(field)
        report["plan_saved"] = False
        suspend(db, report_id, "A detail was added. Reconfirm the overview and reminder times.")
        db.execute("UPDATE reports SET payload=? WHERE id=?", (json.dumps(report), report_id))
        db.execute("INSERT INTO reviews(report_id,field_id,before,after,created) VALUES (?,?,?,?,?)", (report_id, field["id"], "null", json.dumps(field), now_utc().isoformat()))
        return review_state(report, db)


def medication_details(report, group):
    fields = [field for field in report["fields"] if field["group"] == group and field["status"] != "rejected"]
    return fields, {field["label"]: field["value"] for field in fields}


def frequency_count(value):
    text = value.strip().casefold()
    if re.search(r"as needed|when needed|prn|sos", text):
        return None, "As-needed instructions do not create fixed repeating reminders. Record use manually."
    interval = re.search(r"(?:every|each)\s+(\d+)\s*(?:hours?|hrs?|h)\b", text)
    if interval:
        hours = int(interval[1])
        if hours and 24 % hours == 0 and 1 <= 24 // hours <= 8:
            return 24 // hours, f"interval:{hours}"
    shorthand = re.fullmatch(r"([01])\s*-\s*([01])\s*-\s*([01])", text)
    if shorthand:
        return sum(map(int, shorthand.groups())), "shorthand"
    mapping = {"once daily": 1, "once a day": 1, "daily": 1, "twice daily": 2, "twice a day": 2,
               "three times daily": 3, "three times a day": 3, "four times daily": 4, "at bedtime": 1,
               "every morning": 1, "every night": 1}
    if text in mapping:
        return mapping[text], "flexible"
    anchors = list(RELATIVE_TIME.finditer(text))
    remainder = RELATIVE_TIME.sub("", text)
    remainder = re.sub(r"\b(?:and|then|every day)\b|[,;/&.]", "", remainder).strip()
    if anchors and remainder in mapping:
        return mapping[remainder], "relative"
    if anchors and not remainder and len(anchors) <= 8:
        return len(anchors), "relative"
    return None, "Enter the prescribed frequency in the overview. Unclear instructions cannot generate reminder times."


RELATIVE_TIME = re.compile(r"(?:(\d+)\s*(minutes?|mins?|hours?|hrs?)\s+)?\b(before|after|with|at|on)\s+(?:(?:your|the)\s+)?(?:going to\s+)?(breakfast|lunch|dinner|bedtime|sleep(?:ing)?|bed|waking(?: up)?|wake(?: up)?|night|evening meal)\b", re.I)


def relative_times(text, routine):
    entries = []
    seen = set()
    for match in RELATIVE_TIME.finditer(text):
        phrase = match[4].casefold()
        key = "sleep" if phrase in {"bedtime", "sleep", "sleeping", "bed", "night"} else "wake" if phrase.startswith(("wak", "waking")) else "dinner" if phrase == "evening meal" else phrase
        offset = int(match[1]) * (60 if match[2].casefold().startswith(("hour", "hr")) else 1) if match[1] else None
        if offset is not None and (offset >= 1440 or match[3].casefold() not in {"before", "after"}):
            return [], "Check the stated gap before choosing reminder times."
        if offset is None and re.search(r"\b(?:minutes?|mins?|hours?|hrs?)\s*$", text[max(0, match.start()-35):match.start()], re.I):
            return [], "This time gap needs clarification. Enter it as a number of minutes or hours in the overview."
        minute = int(routine[key][:2]) * 60 + int(routine[key][3:])
        if offset is not None:
            minute += offset * (-1 if match[3].casefold() == "before" else 1)
        minute %= 1440
        identity = (key, match[3].casefold(), offset)
        if identity not in seen:
            entries.append({"key": key, "phrase": match[0], "exact": offset is not None, "time": f"{minute // 60:02}:{minute % 60:02}"})
            seen.add(identity)
    return entries, ""


def evenly_spaced(clocks, hours):
    minutes = sorted(int(clock[:2]) * 60 + int(clock[3:]) for clock in clocks)
    return len(minutes) == 1 or all((minutes[(i+1) % len(minutes)] - minute) % 1440 == hours * 60 for i, minute in enumerate(minutes))


def prescribed_times(text):
    result = []
    pattern = r"(?<![\d:])(\d{1,2})(?::([0-5]\d))?\s*(am|pm)\b|(?<![\d:])([01]?\d|2[0-3]):([0-5]\d)(?![\d:])"
    for match in re.finditer(pattern, text, re.I):
        if match[1]:
            hour = int(match[1])
            if not 1 <= hour <= 12:
                continue
            hour = hour % 12 + (12 if match[3].lower() == "pm" else 0)
            result.append(f"{hour:02}:{int(match[2] or 0):02}")
        else:
            result.append(f"{int(match[4]):02}:{int(match[5]):02}")
    return sorted(set(result))


def invalid_clock(text):
    pattern = r"(?<![\d:])(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b|(?<![\d:])(\d{1,2}):(\d{2})(?![\d:])"
    for match in re.finditer(pattern, text, re.I):
        if match[1]:
            if not 1 <= int(match[1]) <= 12 or int(match[2] or 0) > 59:
                return True
        elif int(match[4]) > 23 or int(match[5]) > 59:
            return True
    return False


@router.get("/reports/{report_id}/timing")
def timing(report_id: str, group: str):
    with store.connect() as db:
        report = store.get(report_id, db)
        if not report:
            raise HTTPException(404, "Report not found.")
        revision = fingerprint(report, db)
    routine = get_routine()
    fields, details = medication_details(report, group)
    frequency = details.get("Frequency", "")
    count, mode = frequency_count(frequency)
    instructions = frequency + " " + details.get("Instructions", "")
    source_clocks = prescribed_times(instructions)
    anchors, anchor_error = relative_times(instructions, routine)
    today = now_utc().astimezone(ZoneInfo(routine["timezone"])).date()
    duration = re.fullmatch(r"(?:for\s+)?(\d+)\s*days?", details.get("Duration", "").strip(), re.I)
    end = (today + timedelta(days=int(duration[1]) - 1)).isoformat() if duration and 1 <= int(duration[1]) <= 366 else ""
    clocks = []
    if re.search(r"as needed|when needed|prn|sos", instructions, re.I):
        source_clocks = []
        count = None
        anchors = []
        mode = "As-needed instructions remain manual records, not fixed repeating reminders."
    if source_clocks and count and len(source_clocks) != count:
        mode = "The stated times and frequency need clarification. Check the overview before choosing reminder times."
        count = None
        source_clocks = []
    if source_clocks:
        clocks = sorted(set(source_clocks))
        mode = "Times copied from this document. Check the clock notation and your course start/end dates."
    elif anchor_error:
        mode = anchor_error
    elif anchors:
        proposed = sorted(set(entry["time"] for entry in anchors))
        if not count or len(anchors) != count or len(proposed) != count:
            mode = "The meal/sleep instructions and frequency need clarification. Check the overview before setting reminders."
        elif mode.startswith("interval:") and not evenly_spaced(proposed, int(mode.split(":")[1])):
            mode = "The routine-based times conflict with the prescribed interval. Clarify the instructions first."
        else:
            clocks = proposed
            mode = "Based on your routine: " + "; ".join(f"{entry['phrase']} → {entry['time']}" for entry in anchors) + ". "
            mode += "The stated time gap is preserved. " if any(entry["exact"] for entry in anchors) else ""
            if any(not entry["exact"] for entry in anchors):
                mode += "No exact gap is given for this meal/sleep instruction. Adjust the suggested time to suit your routine. "
    elif count:
        wake = int(routine["wake"][:2]) * 60 + int(routine["wake"][3:])
        if mode.startswith("interval:"):
            spacing = int(mode.split(":")[1]) * 60
            clocks = [f"{((wake + i * spacing) % 1440) // 60:02}:{((wake + i * spacing) % 1440) % 60:02}" for i in range(count)]
            mode = "Suggested from your wake time while preserving the stated interval, including overnight. Confirm with your prescription instructions."
        elif mode == "shorthand":
            values = re.findall(r"[01]", frequency)
            clocks = [routine[key] for bit, key in zip(values, ("breakfast", "lunch", "dinner")) if bit == "1"]
            mode = "Suggested meal times for the stated morning/midday/evening pattern. Confirm what the notation means for this medicine."
        else:
            clocks = {1: [routine["sleep"] if re.search(r"night|bedtime", frequency, re.I) else routine["breakfast"]],
                      2: [routine["breakfast"], routine["dinner"]], 3: [routine["breakfast"], routine["lunch"], routine["dinner"]],
                      4: [routine["breakfast"], routine["lunch"], routine["dinner"], routine["sleep"]]}.get(count, [])
            mode = "Suggested reminder times from your routine, not prescribed clock times. Confirm suitable spacing and food instructions before starting."
    if source_clocks and (anchor_error or any(entry["exact"] and entry["time"] not in clocks for entry in anchors)):
        clocks = []
        mode = anchor_error or "The stated clock time and meal/sleep gap conflict with your saved routine. Check the routine and instructions first."
    if invalid_clock(instructions):
        clocks = []
        mode = "A clock time is invalid. Correct it in the overview before choosing reminders."
    missing = [label for label in ("Name", "Dose", "Frequency") if not details.get(label, "").strip()]
    blocked = missing or [field["label"] for field in fields if field["status"] != "confirmed"]
    return {"revision": revision, "dose": details.get("Dose", ""), "times": clocks, "start": today.isoformat(), "end": end,
            "timezone": routine["timezone"], "duration_days": int(duration[1]) if duration else None, "explanation": mode, "blocked": blocked, "can_schedule": bool(clocks and not blocked and report["plan_saved"])}


@router.post("/reports/{report_id}/reminders", status_code=201)
def start_reminder(report_id: str, draft: PersonalReminder):
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        patient_id = store.require_report_permission(report_id, "edit", db)
        report = store.get(report_id, db)
        if not report["plan_saved"] or draft.revision != fingerprint(report, db):
            raise HTTPException(409, "Confirm the latest prescription overview before starting reminders.")
        fields, details = medication_details(report, draft.group)
        if not fields or any(field["status"] != "confirmed" for field in fields) or any(not details.get(key, "").strip() for key in ("Name", "Dose", "Frequency")):
            raise HTTPException(409, "Fill in and confirm this medicine's name, dose, frequency and unresolved instructions first.")
        if len({field["label"] for field in fields}) != len(fields):
            raise HTTPException(409, "Resolve duplicate medicine details first.")
        count, mode = frequency_count(details["Frequency"])
        instructions = details["Frequency"] + " " + details.get("Instructions", "")
        if invalid_clock(instructions):
            raise HTTPException(422, "Correct the invalid clock time in the overview first.")
        if re.search(r"as needed|when needed|prn|sos", instructions, re.I):
            raise HTTPException(422, "As-needed instructions do not create fixed repeating reminders.")
        prescribed_clocks = prescribed_times(instructions)
        routine = get_routine()
        anchors, anchor_error = relative_times(instructions, routine)
        if prescribed_clocks:
            if count and count != len(prescribed_clocks):
                raise HTTPException(422, "Resolve the conflicting clock times and frequency in the overview first.")
            if draft.times != prescribed_clocks:
                raise HTTPException(422, "The document states clock times. Edit the overview if those instructions were transcribed incorrectly.")
        elif not count or len(draft.times) != count:
            raise HTTPException(422, mode if not count else "The number of reminder times must match the confirmed frequency.")
        if anchor_error:
            raise HTTPException(422, anchor_error)
        if anchors:
            if not prescribed_clocks and len(anchors) != count:
                raise HTTPException(422, "Resolve the conflicting frequency and meal/sleep instructions first.")
            if draft.timezone != routine["timezone"]:
                raise HTTPException(422, "Use your routine's time zone for meal/sleep reminders, or update the routine first.")
            if any(entry["exact"] and entry["time"] not in draft.times for entry in anchors):
                raise HTTPException(422, "Preserve the stated gap from your meal/sleep time. Update your routine if that time has changed.")
        if mode.startswith("interval:"):
            minutes = sorted(int(clock[:2]) * 60 + int(clock[3:]) for clock in draft.times)
            expected = int(mode.split(":")[1]) * 60
            if any((minutes[(i + 1) % len(minutes)] - minutes[i]) % 1440 != expected for i in range(len(minutes))) and len(minutes) > 1:
                raise HTTPException(422, "Keep the prescribed interval between reminders, including overnight.")
        if draft.dose.strip().casefold() != details["Dose"].strip().casefold():
            raise HTTPException(422, "Change the dose in the prescription overview first, then reconfirm it.")
        duration = re.fullmatch(r"(?:for\s+)?(\d+)\s*days?", details.get("Duration", "").strip(), re.I)
        if duration and (draft.end - draft.start).days + 1 != int(duration[1]):
            raise HTTPException(422, "The chosen course dates must match the confirmed duration. Edit incorrect source details in the overview first.")
        if draft.end < now_utc().astimezone(ZoneInfo(draft.timezone)).date():
            raise HTTPException(422, "This reminder period has already ended.")
        existing = db.execute("""SELECT schedules.* FROM schedules JOIN report_access ON report_access.report_id=schedules.report_id
            JOIN episodes ON episodes.id=report_access.episode_id WHERE episodes.patient_id=? AND status IN ('active','approved')""", (patient_id,)).fetchall()
        for row in existing:
            payload = json.loads(row["payload"])
            if payload["name"].strip().casefold() == details["Name"].strip().casefold() and payload["start"] <= draft.end.isoformat() and payload["end"] >= draft.start.isoformat():
                raise HTTPException(409, "An overlapping reminder for this medicine already exists. Stop the older reminder first.")
        payload = draft.model_dump(mode="json", exclude={"confirmed", "revision"})
        payload.update(name=details["Name"], strength=details.get("Strength", ""), source=fields, confirmation="User-confirmed personal reminder; not clinical approval")
        if anchors:
            payload["routine_snapshot"] = routine
        identity = uuid4().hex
        db.execute("""INSERT INTO schedules(id,report_id,medication_group,owner_id,clinician_id,payload,fingerprint,status,consent,created_at,reason,authority)
            VALUES (?,?,?,?,?,?,?,'active',1,?,'','personal')""", (identity, report_id, draft.group, store.current_user.get(), store.current_user.get(), json.dumps(payload), fingerprint(report, db), now_utc().isoformat()))
        store.audit(db, patient_id, "personal_reminder_started", report_id, identity)
        return list_schedules_in_transaction(db, report_id)
