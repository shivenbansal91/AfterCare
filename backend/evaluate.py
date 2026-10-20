import json
from pathlib import Path
from tempfile import TemporaryDirectory

from .extraction import baseline, read_document
from .sample import create_sample


def evaluate():
    results = []
    with TemporaryDirectory() as directory:
        for variant in range(6):
            path = Path(directory) / f"sample-{variant}.pdf"
            expected = create_sample(path, variant)
            fields = baseline(read_document(path))
            results.append({
                "variant": variant, "fields": len(fields),
                "patient_exact": any(f.label == "Name" and f.group == "Patient" and f.value == expected["patient"] for f in fields),
                "source_linked": sum(f.source is not None for f in fields),
                "invented_missing_duration": any(f.group == "Medication 2" and f.label == "Duration" for f in fields),
            })
    return {"scope": "Six generated fixtures, two spacings; sanity check only, not a held-out clinical benchmark", "results": results}


if __name__ == "__main__":
    print(json.dumps(evaluate(), indent=2))
