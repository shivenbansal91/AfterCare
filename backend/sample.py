from datetime import date, timedelta
from pathlib import Path

import pymupdf


def create_sample(path: Path, variant: int = 0, scanned: bool = False) -> dict:
    today = date.today()
    patient = ["Aarav Mehta", "Maya Shah", "Rohan Kapoor"][variant % 3]
    lines = [
        "FICTIONAL DOCUMENT - FOR SOFTWARE TESTING ONLY",
        "Hospital: Willowbrook Medical Centre",
        "Discharge summary",
        f"Patient: {patient}", f"Age: {32 + variant}",
        "Doctor: Dr. Ananya Rao", f"Discharge date: {today.isoformat()}",
        "Medication: Amoxicillin | 500 mg | 1 capsule | Twice daily | 5 days | After food",
        "Medication: Paracetamol | 500 mg | 1 tablet | As needed | Not stated | For pain",
        f"Follow-up: {(today + timedelta(days=7)).isoformat()} - Dr. Ananya Rao",
        "Tests: Complete blood count before follow-up",
        "Instructions: Follow the discharge instructions. Contact the care team for clarification.",
        "No exact clock times are prescribed. Do not infer a reminder schedule.",
    ]
    document = pymupdf.open()
    page = document.new_page(width=720, height=900)
    expected = []
    for index, line in enumerate(lines):
        y = 70 + index * (40 if variant % 2 else 37)
        size = 10 if index == 0 else 11
        page.insert_text((35, y), line, fontsize=size, color=(0.1, 0.28, 0.21))
        expected.append({"text": line, "page": 0, "boxes": [list(rect) for rect in page.search_for(line)]})
    if scanned or path.suffix == ".png":
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2))
        if path.suffix == ".png":
            pixmap.save(path)
        else:
            with pymupdf.open() as scan:
                scan.new_page(width=page.rect.width, height=page.rect.height).insert_image(page.rect, stream=pixmap.tobytes("png"))
                scan.save(path)
    else:
        document.save(path)
    document.close()
    return {"patient": patient, "lines": expected}
