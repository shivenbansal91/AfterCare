import json
import os
import re

import httpx
from fastapi import APIRouter, HTTPException

from . import store

router = APIRouter(prefix="/api/reports")
REFERENCES = {
    "amoxicillin": ("amoxicillin", ["A penicillin antibiotic used for certain bacterial infections, including some chest and dental infections."]),
    "paracetamol": ("paracetamol-for-adults", ["A pain reliever that also helps reduce a high temperature."]),
    "ibuprofen": ("ibuprofen-for-adults", ["An anti-inflammatory pain reliever used for pain, swelling and fever."]),
    "escitalopram": ("escitalopram", ["An antidepressant used to treat depression and some anxiety conditions."]),
    "metronidazole": ("metronidazole/about-metronidazole", ["An antibiotic used for certain bacterial and parasitic infections."]),
    "levothyroxine": ("levothyroxine", ["A thyroid hormone medicine used to treat an underactive thyroid."]),
    "metformin": ("metformin", ["A medicine that lowers blood sugar and is commonly used to treat type 2 diabetes."]),
    "atorvastatin": ("atorvastatin", ["A statin medicine used to lower cholesterol and help prevent cardiovascular disease."]),
    "omeprazole": ("omeprazole", ["A medicine that reduces stomach acid, used for conditions such as acid reflux and stomach ulcers."]),
    "amlodipine": ("amlodipine", ["A medicine used to treat high blood pressure and help prevent angina."]),
    "cetirizine": ("cetirizine/about-cetirizine", ["An antihistamine used to relieve allergy symptoms."]),
    "fluconazole": ("fluconazole", ["An antifungal medicine used for thrush and certain other fungal infections."]),
    "clotrimazole": ("clotrimazole", ["An antifungal medicine used for certain fungal infections, including thrush and some fungal skin infections."]),
}


def reference_name(name):
    text = name.casefold().strip()
    text = re.sub(r"\b\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml)\b", "", text)
    text = re.sub(r"\b(?:tablets?|capsules?)\b", "", text)
    text = " ".join(text.split())
    return text if text in REFERENCES else None


@router.get("/{report_id}/medicines/info")
def medicine_information(report_id: str, group: str):
    with store.connect() as db:
        report = store.get(report_id, db)
        if not report:
            raise HTTPException(404, "Report not found.")
    fields = [field for field in report["fields"] if field["group"] == group and field["status"] != "rejected"]
    name = next((field["value"] for field in fields if field["label"] == "Name"), "")
    reviewed = [field for field in fields if field["status"] == "confirmed"]
    indication = next((field for field in reviewed if field["label"].casefold() in {"indication", "reason", "purpose"}), None)
    if indication is None:
        indication = next((field for field in reviewed if field["label"] == "Instructions" and re.match(r"^for\s+[A-Za-z]", field["value"], re.I)
                           and not re.match(r"^for\s+(?:(?:one|two|three|four|five|six|seven|eight|nine|ten|a|an)\s+(?:days?|weeks?|months?|hours?|times?)\b|(?:oral|external|topical|intravenous|intramuscular)\b)", field["value"], re.I)), None)
    context_labels = {"diagnosis", "condition", "reason for admission", "main problem", "problem", "symptoms", "assessment", "reason for visit"}
    context = [{"id": field["id"], "label": field["label"], "value": field["value"], "source": field.get("source"),
                "origin": "document" if field.get("source") else "manual", "status": field["status"]}
               for field in report["fields"] if not field["group"].startswith("Medication") and field["label"].casefold() in context_labels
               and field["status"] != "rejected" and field["value"].strip()]
    matched = reference_name(name)
    result = {"name": name, "matched": bool(matched), "facts": [], "source_url": None, "source_name": "NHS Medicines",
              "checked_on": "2026-10-19", "method": "reference", "reason": indication["value"] if indication else None,
              "reason_origin": ("document" if indication.get("source") else "manual") if indication else None,
              "reason_source": indication.get("source") if indication else None, "context": context,
              "context_notice": "The report lists these problems separately; it does not explicitly link this medicine to them." if context and not indication else None,
              "notice": "General information, not an explanation of why this was prescribed to you. Follow your own prescription and medicine leaflet."}
    if not matched:
        result["notice"] = "No exact match in the offline reference collection. Check the medicine leaflet or ask a pharmacist; the app will not guess from a similar name."
        return result
    slug, facts = REFERENCES[matched]
    result.update(facts=facts, source_url=f"https://www.nhs.uk/medicines/{slug}/")
    return result


@router.post("/{report_id}/medicines/explain")
def explain_from_reference(report_id: str, group: str):
    result = medicine_information(report_id, group)
    if not result["matched"]:
        return result
    # Phi can select supported facts; generated medical claims never reach the UI.
    try:
        response = httpx.post(os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434") + "/api/chat", timeout=12, json={
            "model": os.environ.get("OLLAMA_MODEL", "phi4-mini:latest"), "stream": False,
            "format": {"type": "object", "properties": {"fact_ids": {"type": "array", "items": {"type": "integer"}}}, "required": ["fact_ids"]},
            "options": {"temperature": 0, "num_predict": 80},
            "messages": [{"role": "system", "content": "Select IDs of useful general-use facts. Return only fact_ids. Do not diagnose, prescribe, add facts or infer a person's condition."},
                         {"role": "user", "content": json.dumps({"medicine": reference_name(result["name"]), "facts": dict(enumerate(result["facts"])),
                            "report_context": result["context"], "stated_reason": result["reason"]})}],
        })
        response.raise_for_status()
        selected = json.loads(response.json()["message"]["content"])["fact_ids"]
        if selected and all(type(index) is int and 0 <= index < len(result["facts"]) for index in selected):
            result["facts"] = [result["facts"][index] for index in dict.fromkeys(selected)]
            result["method"] = "local_phi_grounded_selection"
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        result["method"] = "reference_fallback"
    return result
