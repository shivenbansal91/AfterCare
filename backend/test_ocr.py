import pytest

from .extraction import tesseract_path


@pytest.mark.skipif(tesseract_path() is None, reason="Local Tesseract is not installed")
@pytest.mark.parametrize("kind", ["scan", "photo"])
def test_local_ocr_extracts_fields_and_valid_source_boxes(client, kind):
    response = client.post(f"/api/reports/sample?kind={kind}")
    assert response.status_code == 200
    report = response.json()
    assert report["pages"][0]["method"] == "ocr"
    assert len(report["fields"]) == 19
    assert any("OCR" in warning for warning in report["warnings"])
    assert any(f["group"] == "Patient" and f["value"] == "Aarav Mehta" for f in report["fields"])
    assert not any(f["group"] == "Medication 2" and f["label"] == "Duration" for f in report["fields"])
    for field in report["fields"]:
        source = field["source"]
        page = report["pages"][source["page"]]
        for x0, y0, x1, y1 in source["boxes"]:
            assert 0 <= x0 < x1 <= page["width"] + 1
            assert 0 <= y0 < y1 <= page["height"] + 1
