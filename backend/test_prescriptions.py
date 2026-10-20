from pathlib import Path

import pymupdf
import pytest

from . import main, store
from .extraction import baseline, read_document, tesseract_path

SAMPLE = Path(__file__).resolve().parents[1] / "samples/prescription-template-sample.jpg"
needs_ocr = pytest.mark.skipif(tesseract_path() is None, reason="Local Tesseract is not installed")


def prescription_pdf(path):
    with pymupdf.open() as document:
        page = document.new_page(width=600, height=500)
        page.insert_text((25, 35), "Patient's name: Fictional patient", fontsize=11)
        page.insert_text((25, 55), "Doctor's name: Fictional clinician", fontsize=11)
        xs = [20, 185, 260, 420, 580]
        ys = [90, 125, 205, 285]
        for y in ys:
            page.draw_line((20, y), (580, y), color=(.45, .45, .45), width=.7)
        for x in xs:
            page.draw_line((x, 90), (x, 285), color=(.45, .45, .45), width=.7)
        rows = [
            ["Medication", "Dosage", "Frequency and duration", "Instructions"],
            ["Amoxicillin 250mg capsules", "1 capsule", "Twice daily for 7 days", "After food. Keep in original pack."],
            ["Paracetamol 500mg tablets", "2 tablets", "As needed for 3 days", "Follow the source instructions."],
        ]
        for index, row in enumerate(rows):
            for column, text in enumerate(row):
                result = page.insert_textbox((xs[column] + 5, ys[index] + 5, xs[column + 1] - 5, ys[index + 1] - 4), text, fontsize=10)
                assert result >= 0
        document.save(path)


@needs_ocr
def test_attached_prescription_keeps_complete_instructions_and_cell_evidence(client):
    response = client.post("/api/reports", files={"file": (SAMPLE.name, SAMPLE.read_bytes(), "image/jpeg")})
    assert response.status_code == 200
    report = response.json()
    fields = {(f["group"], f["label"]): f for f in report["fields"]}
    assert fields["Patient", "Name"]["value"] == "Karlene Hizon"
    assert fields["Patient", "Date of birth"]["value"] == "March 5, 1953"
    assert fields["Care team", "Doctor"]["value"] == "Anna Ludwig, MD"
    expected = {"Name": "Ibuprofen 400mg tablets", "Strength": "400mg", "Dose": "1 tablet",
                "Frequency": "Take orally, every 6 hours", "Duration": "5 days",
                "Instructions": "Take with food. Do not exceed 2400mg in 24 hours."}
    for label, value in expected.items():
        field = fields["Medication 1", label]
        assert field["value"] == value and field["status"] == "pending"
        assert value in field["source"]["text"]
    assert "avoid other NSAIDs" in fields["Recovery", "Instructions"]["value"]
    assert not any(f["label"] in {"Age", "Discharge date"} for f in report["fields"])
    for field in report["fields"]:
        page = report["pages"][field["source"]["page"]]
        assert all(0 <= x0 < x1 <= page["width"] and 0 <= y0 < y1 <= page["height"] for x0, y0, x1, y1 in field["source"]["boxes"])
    assert not report["plan_saved"]
    assert client.post(f"/api/reports/{report['id']}/plan").status_code == 409


@pytest.mark.parametrize("scan", [False, True])
def test_multiple_medication_rows_do_not_mix_columns(tmp_path, scan):
    if scan and not tesseract_path():
        pytest.skip("Local Tesseract is not installed")
    path = tmp_path / "table.pdf"
    prescription_pdf(path)
    if scan:
        with pymupdf.open(path) as document:
            content = document[0].get_pixmap(matrix=pymupdf.Matrix(2, 2)).tobytes("png")
        path = tmp_path / "table.png"
        path.write_bytes(content)
    pages = read_document(path)
    fields = {(f.group, f.label): f for f in baseline(pages)}
    assert fields["Medication 1", "Dose"].value == "1 capsule"
    assert fields["Medication 1", "Duration"].value == "7 days"
    assert fields["Medication 2", "Dose"].value == "2 tablets"
    assert fields["Medication 2", "Duration"].value == "3 days"
    assert fields["Medication 1", "Strength"].value == "250mg"
    scale = pages[0]["width"] / 600
    for group in ["Medication 1", "Medication 2"]:
        assert all(185 * scale < box[0] < box[2] < 260 * scale for box in fields[group, "Dose"].source.boxes)
        assert all(420 * scale < box[0] < box[2] < 580 * scale for box in fields[group, "Instructions"].source.boxes)


def test_concentration_and_duration_qualifiers_are_not_dropped():
    def cell(text):
        return {"text": text, "words": [{"text": text, "box": [10, 10, 100, 20]}]}
    pages = [{"number": 0, "lines": [], "tables": [{"rows": [{
        "Name": cell("Fictional medicine 100mg/5mL solution"),
        "Frequency and duration": cell("Once daily for 5 days only if needed"),
    }]}]}]
    fields = {f.label: f.value for f in baseline(pages)}
    assert fields["Strength"] == "100mg/5mL"
    assert fields["Frequency"] == "Once daily for 5 days only if needed"
    assert fields["Duration"] == "5 days"


@needs_ocr
def test_empty_report_can_be_read_again_without_replacing_reviewed_fields(client, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(main, "baseline", lambda pages: [])
        report = client.post("/api/reports", files={"file": (SAMPLE.name, SAMPLE.read_bytes(), "image/jpeg")}).json()
    assert report["fields"] == []
    assert "Text was read" in report["warnings"][0]
    prefix = f"/api/reports/{report['id']}"
    updated = client.post(prefix + "/reread")
    assert updated.status_code == 200
    assert len(updated.json()["fields"]) >= 12
    assert updated.json()["created"] == report["created"]
    assert client.get(prefix + "/file").content == SAMPLE.read_bytes()
    field = updated.json()["fields"][0]
    client.patch(f"{prefix}/fields/{field['id']}", json={"status": "confirmed", "value": field["value"]})
    assert client.post(prefix + "/reread").status_code == 409
    assert client.get(prefix).json()["fields"][0]["status"] == "confirmed"


def test_retry_does_not_overwrite_a_concurrent_extraction(client, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(main, "baseline", lambda pages: [])
        report = client.post("/api/reports/sample").json()
    original = main.baseline

    def another_extraction_finishes(pages):
        fields = original(pages)
        store.save({**report, "fields": [f.model_dump() for f in fields]})
        return fields

    monkeypatch.setattr(main, "baseline", another_extraction_finishes)
    assert client.post(f"/api/reports/{report['id']}/reread").status_code == 409
    assert len(client.get(f"/api/reports/{report['id']}").json()["fields"]) == 19
