import os
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import store, vault
from backend.auth import encoded_password
from backend.backup import installation_lock
from backend.main import process
from backend.personal import personal_space
from backend.sample import create_sample


def main():
    if os.environ.get("AFTERCARE_PUBLIC_ORIGIN"):
        raise SystemExit("The fictional demo installer is available only on a local installation.")
    with installation_lock(store.DATA):
        vault.initialize(store.DATA)
        with store.connect() as db:
            if db.execute("SELECT 1 FROM users WHERE username IN ('aftercare-demo','aftercare-helper')").fetchone():
                raise SystemExit("Demo accounts already exist. Existing records were left unchanged.")
            owner, helper = uuid4().hex, uuid4().hex
            db.execute("INSERT INTO users VALUES (?,?,?)", (owner, "aftercare-demo", encoded_password("Aftercare-demo-2026!")))
            db.execute("INSERT INTO users VALUES (?,?,?)", (helper, "aftercare-helper", encoded_password("Aftercare-helper-2026!")))
        token = store.current_user.set(owner)
        try:
            context = personal_space()["personal"]
            path = store.DATA / f"{uuid4().hex}.pdf"
            create_sample(path)
            process(path, "Fictional prescription walkthrough.pdf", "baseline", context["episode_id"], sample=True)
        finally:
            store.current_user.reset(token)
    print("Created fictional owner and caretaker accounts with a prescription for review.")
    print("No active reminders or sharing grants were created.")
    print("Owner: aftercare-demo / Aftercare-demo-2026!")
    print("Caretaker: aftercare-helper / Aftercare-helper-2026!")


if __name__ == "__main__":
    main()
