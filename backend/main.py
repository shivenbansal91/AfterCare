import asyncio
import html
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
import pymupdf
from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import store, vault, config
from .reminders import router as reminders_router, worker
from .auth import router as auth_router, session_user
from .backup import installation_lock
from .care import router as care_router, require_episode, workspace
from .extraction import baseline, extract_with_ollama, read_document, render_page, tesseract_path
from .models import Review
from .medicine_info import router as medicine_info_router
from .reports import router as reports_router
from .sample import create_sample
from .tracking import router as tracking_router
from .schedules import router as schedules_router
from .personal import router as personal_router, migrate_personal_mode, personal_space

@asynccontextmanager
async def lifespan(app):
    config.validate()
    with installation_lock(store.DATA):
        vault.initialize(store.DATA)
        with store.connect():
            pass
        migrate_personal_mode()
        stop = asyncio.Event()
        task = asyncio.create_task(worker(stop))
        try:
            yield
        finally:
            stop.set()
            await task


app = FastAPI(title="AfterCare Local", version="2.0.0", lifespan=lifespan)
app.include_router(tracking_router)
app.include_router(auth_router)
app.include_router(care_router)
app.include_router(reports_router)
app.include_router(schedules_router)
app.include_router(personal_router)
app.include_router(medicine_info_router)
app.include_router(reminders_router)


@app.middleware("http")
async def local_only(request: Request, call_next):
    if request.url.hostname not in config.allowed_hosts():
        return JSONResponse({"detail": "Unrecognized host"}, status_code=403)
    origin = request.headers.get("origin")
    if origin and origin not in config.allowed_origins():
        return Response("Unrecognized origin", status_code=403)
    if request.method not in {"GET", "HEAD", "OPTIONS"} and not origin:
        return JSONResponse({"detail": "A same-origin request is required."}, status_code=403)
    public = {"/api/health", "/api/auth/session", "/api/auth/login", "/api/auth/register", "/api/auth/recover"}
    user = None
    if request.url.path.startswith("/api/") and request.url.path not in public:
        user = session_user(request)
        if not user:
            return JSONResponse({"detail": "Sign in to continue."}, status_code=401, headers={"Cache-Control": "no-store"})
    token = store.current_user.set(user["id"] if user else None)
    try:
        response = await call_next(request)
    finally:
        store.current_user.reset(token)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    if config.public_origin():
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response


def require_report(report_id: str):
    report = store.get(report_id)
    if not report:
        raise HTTPException(404, "Report not found.")
    return report


def selected_episode(episode_id: str | None):
    if episode_id:
        return require_episode(episode_id)["id"]
    return personal_space()["personal"]["episode_id"]


def process(path: Path, name: str, engine: str, episode_id: str, sample=False, original=None):
    if engine not in {"auto", "baseline", "ollama"}:
        raise HTTPException(400, "Choose baseline or ollama.")
    if sample and not path.read_bytes().startswith(vault.MAGIC):
        vault.write(path, path.read_bytes())
    try:
        with vault.readable(path) as readable:
            pages = read_document(readable)
        fields = extract_with_ollama(pages) if engine == "ollama" else baseline(pages)
        actual_engine = "ollama" if engine == "ollama" else "baseline"
        automatic_warning = None
        if engine == "auto" and os.environ.get("AFTERCARE_AUTO_AI", "1") == "1" and not any(field.group.startswith("Medication") for field in fields):
            try:
                tags = httpx.get(os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434") + "/api/tags", timeout=1).json()
                if os.environ.get("OLLAMA_MODEL", "phi4-mini:latest") in {model["name"] for model in tags.get("models", [])}:
                    fields = extract_with_ollama(pages, timeout=45)
                    actual_engine = "hybrid"
            except (httpx.HTTPError, ValueError, RuntimeError, KeyError):
                automatic_warning = "Some details may need to be entered manually. Check the original document."
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    except httpx.HTTPError as error:
        raise HTTPException(503, "Local Ollama could not finish extraction. Check that Ollama is running, or choose the rule baseline.") from error
    except (RuntimeError, pymupdf.FileDataError) as error:
        raise HTTPException(422, "This file could not be read. Use an unlocked PDF, PNG or JPEG.") from error
    report = {
        "id": path.stem, "name": name, "file": path.name, "engine": actual_engine, "sample": sample, "episode_id": episode_id,
        "created": original["created"] if original else datetime.now(timezone.utc).isoformat(), "pages": pages,
        "fields": [field.model_dump() for field in fields], "plan_saved": False,
        "warnings": [automatic_warning] if automatic_warning else [],
    }
    if not fields:
        readable = any(re.search(r"[A-Za-z0-9]", line["text"]) for page in pages for line in page["lines"])
        report["warnings"].append("Text was read, but no care details could be identified in this layout. Check the original and add missing details."
                                  if readable else "No readable text was found. Try a clearer photo or scan; the original file is still available.")
    if any(page["method"] == "ocr" for page in pages):
        report["warnings"].append("This report used OCR. Check names, numbers and instructions carefully against the image.")
    vault.write(path, vault.read(path))
    store.save(report, empty_only=original is not None)
    return report


@app.get("/api/health")
def health():
    try:
        tags = httpx.get(os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434") + "/api/tags", timeout=2).json()
        models = [model["name"] for model in tags.get("models", [])]
    except (httpx.HTTPError, ValueError):
        models = []
    return {"status": "ok", "models": models, "model": os.environ.get("OLLAMA_MODEL", "phi4-mini:latest"), "ocr_available": bool(tesseract_path())}


@app.get("/api/reports")
def reports():
    return store.all_reports()


@app.post("/api/reports/sample")
def sample(engine: str = "auto", kind: str = "pdf", episode_id: str | None = None):
    episode_id = selected_episode(episode_id)
    if engine not in {"auto", "baseline", "ollama"}:
        raise HTTPException(400, "Choose baseline or ollama.")
    if kind not in {"pdf", "scan", "photo"}:
        raise HTTPException(400, "Choose pdf, scan or photo.")
    extension = ".png" if kind == "photo" else ".pdf"
    path = store.DATA / f"{uuid4().hex}{extension}"
    create_sample(path, scanned=kind == "scan")
    try:
        name = f"Willowbrook · fictional {kind}{extension}"
        return process(path, name, engine, episode_id, sample=True)
    except Exception:
        path.unlink(missing_ok=True)
        raise


@app.post("/api/reports")
def upload(file: UploadFile, engine: str = "auto", episode_id: str | None = None):
    episode_id = selected_episode(episode_id)
    extension = Path(file.filename or "").suffix.lower()
    if extension not in {".pdf", ".png", ".jpg", ".jpeg"}:
        raise HTTPException(415, "Upload a PDF, PNG or JPEG.")
    content = file.file.read(12 * 1024 * 1024 + 1)
    if not content or len(content) > 12 * 1024 * 1024:
        raise HTTPException(413, "Choose a non-empty file smaller than 12 MB.")
    path = store.DATA / f"{uuid4().hex}{extension}"
    vault.write(path, content)
    try:
        return process(path, Path(file.filename).name, engine, episode_id)
    except Exception:
        path.unlink(missing_ok=True)
        raise


@app.get("/api/reports/{report_id}")
def get_report(report_id: str):
    return require_report(report_id)


@app.post("/api/reports/{report_id}/reread")
def reread(report_id: str):
    report = require_report(report_id)
    store.require_report_permission(report_id, "edit")
    if report["fields"]:
        raise HTTPException(409, "This report already has extracted details. Upload a separate copy to keep its review and activity history intact.")
    return process(store.DATA / report["file"], report["name"], "baseline", report["episode_id"],
                   sample=report["sample"], original=report)


@app.get("/api/reports/{report_id}/file")
def original(report_id: str, inline: bool = False):
    report = require_report(report_id)
    if vault.source_name(report) is None:
        raise HTTPException(404, "This medicine was entered manually; no document was uploaded.")
    response = FileResponse(store.DATA / report["file"], filename=report["name"],
                            content_disposition_type="inline" if inline else "attachment")
    return Response(vault.read(store.DATA / report["file"]), media_type=response.media_type, headers=dict(response.headers))


@app.get("/api/reports/{report_id}/pages/{page}")
def page_image(report_id: str, page: int):
    report = require_report(report_id)
    if not 0 <= page < len(report["pages"]):
        raise HTTPException(404, "Page not found.")
    with vault.readable(store.DATA / report["file"]) as readable:
        return Response(render_page(readable, page), media_type="image/png")


@app.patch("/api/reports/{report_id}/fields/{field_id}")
def review_field(report_id: str, field_id: str, change: Review):
    report = require_report(report_id)
    store.require_report_permission(report_id, "edit")
    field = next((f for f in report["fields"] if f["id"] == field_id), None)
    if field is None:
        raise HTTPException(404, "Field not found.")
    if change.status == "confirmed" and not change.value.strip():
        raise HTTPException(422, "A confirmed field cannot be empty.")
    before = dict(field)
    field.update(change.model_dump())
    report["plan_saved"] = False
    store.review(report, field, before)
    return report


@app.get("/api/reports/{report_id}/history")
def history(report_id: str):
    require_report(report_id)
    return store.history(report_id)


@app.post("/api/reports/{report_id}/plan")
def save_plan(report_id: str):
    report = require_report(report_id)
    store.require_report_permission(report_id, "edit")
    if not report["fields"] or any(field["status"] == "pending" for field in report["fields"]):
        raise HTTPException(409, "Review each extracted field before saving a plan.")
    if not any(field["status"] == "confirmed" for field in report["fields"]):
        raise HTTPException(409, "Confirm at least one field before saving a plan.")
    previous = dict(report)
    report["plan_saved"] = True
    store.save(report, expected=previous)
    return report


@app.get("/api/reports/{report_id}/plan", response_class=HTMLResponse)
def print_plan(report_id: str):
    report = require_report(report_id)
    if not report["plan_saved"]:
        raise HTTPException(409, "Save a reviewed plan first.")
    groups = {}
    unresolved = []
    for field in report["fields"]:
        if field["status"] == "confirmed":
            groups.setdefault(field["group"], []).append(field)
        elif field["status"] == "clarify":
            unresolved.append(field)
    content = "".join(
        f"<h2>{html.escape(group)}</h2><dl>" + "".join(
            f"<dt>{html.escape(f['label'])}</dt><dd>{html.escape(f['value'])}</dd>" for f in fields
        ) + "</dl>" for group, fields in groups.items()
    )
    clarification = "".join(f"<li>{html.escape(f['group'] + ' / ' + f['label'])}: {html.escape(f['value'])}</li>" for f in unresolved)
    return f"""<!doctype html><html><head><title>AfterCare recovery plan</title>
    <style>body{{font:16px/1.6 system-ui;max-width:760px;margin:40px auto;padding:24px;color:#183e2d}}h2{{border-bottom:1px solid #ddd}}dt{{font-weight:600}}dd{{margin:0 0 12px}}@media print{{button{{display:none}}}}</style></head>
    <body><button onclick="window.print()">Print / Save as PDF</button><h1>Your recovery plan</h1>
    <p>AfterCare · {'Manually entered details; no document uploaded' if report.get('kind') == 'manual' else 'Reviewed transcription'} · Non-clinically-validated prototype</p>
    <p>{'Entry' if report.get('kind') == 'manual' else 'Source'}: {html.escape(report['name'])}</p>{content}
    <h2>Needs clinical clarification</h2><ul>{clarification or '<li>No fields flagged. Missing information may still exist in the source.</li>'}</ul>
    <p>Review confirms transcription only, not clinical appropriateness. Personal reminders are managed separately in AfterCare. Refer to the original discharge instructions and your care team.</p></body></html>"""


if os.environ.get("AFTERCARE_SERVE_FRONTEND") == "1":
    app.mount("/", StaticFiles(directory=Path(__file__).resolve().parents[1] / "frontend/dist/client", html=True), name="frontend")
