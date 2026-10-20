import json

import httpx
from .extraction import baseline, extract_with_ollama, read_document
from .sample import create_sample


def test_sample_source_and_missing_duration(client):
    response = client.post("/api/reports/sample")
    assert response.status_code == 200
    report = response.json()
    assert len(report["fields"]) == 19
    assert all(f["source"]["boxes"] and f["status"] == "pending" for f in report["fields"])
    assert not any(f["group"] == "Medication 2" and f["label"] == "Duration" for f in report["fields"])
    image = client.get(f"/api/reports/{report['id']}/pages/0")
    assert image.headers["content-type"] == "image/png"


def test_plan_review_audit_and_invalidation(client):
    report = client.post("/api/reports/sample").json()
    prefix = f"/api/reports/{report['id']}"
    assert client.post(f"{prefix}/plan").status_code == 409
    for index, field in enumerate(report["fields"]):
        status = "clarify" if index == 2 else "confirmed"
        result = client.patch(f"{prefix}/fields/{field['id']}", json={"value": field["value"], "status": status})
        assert result.status_code == 200
    assert len(client.get(f"{prefix}/history").json()) == len(report["fields"])
    assert client.post(f"{prefix}/plan").json()["plan_saved"]
    assert "Needs clinical clarification" in client.get(f"{prefix}/plan").text
    field = report["fields"][0]
    client.patch(f"{prefix}/fields/{field['id']}", json={"value": "<script>bad()</script>", "status": "confirmed"})
    assert client.get(f"{prefix}/plan").status_code == 409
    client.post(f"{prefix}/plan")
    assert "<script>bad()" not in client.get(f"{prefix}/plan").text
    assert "&lt;script&gt;" in client.get(f"{prefix}/plan").text


def test_upload_validation_and_lookup(client):
    assert client.post("/api/reports", files={"file": ("bad.txt", b"hello")}).status_code == 415
    assert client.post("/api/reports", files={"file": ("empty.pdf", b"")}).status_code == 413
    assert client.post("/api/reports", files={"file": ("broken.pdf", b"not a pdf")}).status_code == 422
    assert client.get("/api/reports/missing").status_code == 404
    assert client.post("/api/reports/sample?engine=external").status_code == 400


def test_cross_origin_rejected(client):
    assert client.post("/api/reports/sample", headers={"Origin": "https://untrusted.example"}).status_code == 403


def test_pdf_upload_keeps_source_after_correction(client, tmp_path):
    path = tmp_path / "input.pdf"
    create_sample(path)
    response = client.post("/api/reports", files={"file": ("input.pdf", path.read_bytes(), "application/pdf")})
    assert response.status_code == 200
    report = response.json()
    field = next(f for f in report["fields"] if f["group"] == "Patient" and f["label"] == "Name")
    updated = client.patch(f"/api/reports/{report['id']}/fields/{field['id']}", json={"value": "Corrected name", "status": "confirmed"}).json()
    correction = next(f for f in updated["fields"] if f["id"] == field["id"])
    assert correction["source"] == field["source"]
    assert "Aarav Mehta" in correction["source"]["text"]
    assert client.get(f"/api/reports/{report['id']}/file").content == path.read_bytes()
    assert client.get(f"/api/reports/{report['id']}/file?inline=true").headers["content-disposition"].startswith("inline;")


def test_photo_reports_missing_ocr(client, monkeypatch):
    from io import BytesIO
    from PIL import Image
    from . import extraction

    monkeypatch.delenv("TESSERACT_CMD", raising=False)
    monkeypatch.setattr(extraction, "tesseract_path", lambda: None)
    image = BytesIO()
    Image.new("RGB", (200, 100), "white").save(image, "PNG")
    response = client.post("/api/reports", files={"file": ("scan.png", image.getvalue(), "image/png")})
    assert response.status_code == 422
    assert "needs OCR" in response.json()["detail"]


def test_model_output_requires_exact_source(tmp_path, monkeypatch):
    path = tmp_path / "sample.pdf"
    create_sample(path)
    pages = read_document(path)
    output = {"fields": [
        {"group": "Patient", "label": "Name", "value": "Aarav Mehta", "quote": "Patient: Aarav Mehta"},
        {"group": "Medication 1", "label": "Frequency", "value": "Every hour", "quote": "Medication: Amoxicillin"},
        {"group": "Patient", "label": "Age", "value": "99", "quote": "Age: 99"},
        {"group": "Medication", "label": "Name", "value": "Amoxicillin", "quote": "Medication: Amoxicillin"},
        {"group": "Medication", "label": "Strength", "value": "500 mg", "quote": "Medication: Amoxicillin"},
        {"group": "Medication", "label": "Name", "value": "Paracetamol", "quote": "Medication: Paracetamol"},
        {"group": "Medication", "label": "Strength", "value": "500 mg", "quote": "Medication: Paracetamol"},
    ]}
    monkeypatch.setenv("OLLAMA_URL", "http://ollama:11434")
    def fake_post(*args, **kwargs):
        assert args[0] == "http://ollama:11434/api/chat"
        return httpx.Response(200, json={"message": {"content": json.dumps(output)}}, request=httpx.Request("POST", "http://127.0.0.1:11434"))
    monkeypatch.setattr(httpx, "post", fake_post)
    fields = extract_with_ollama(pages)
    assert not any(f.value in {"Every hour", "99"} for f in fields)
    assert [(f.group, f.value) for f in fields if f.label == "Strength"] == [("Medication 1", "500 mg"), ("Medication 2", "500 mg")]
    assert any(f.group == "Patient" and f.label == "Name" and f.value == "Aarav Mehta" for f in fields)


def test_unrecognized_layout_abstains(tmp_path):
    import pymupdf
    path = tmp_path / "unknown.pdf"
    with pymupdf.open() as document:
        document.new_page().insert_text((50, 60), "An unclear prescription with no supported labels")
        document.save(path)
    assert baseline(read_document(path)) == []
