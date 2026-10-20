import argparse
from datetime import datetime, timezone

from . import store
from .backup import installation_lock


def main():
    parser = argparse.ArgumentParser(description="Offline clinician credential administration; stop the API first.")
    parser.add_argument("action", choices=["verify-clinician", "revoke-clinician"])
    parser.add_argument("username")
    parser.add_argument("--name")
    parser.add_argument("--registration")
    parser.add_argument("--verified-by")
    parser.add_argument("--evidence", help="Reference to the independently checked identity/license record; never a self-attestation.")
    parser.add_argument("--valid-until", help="YYYY-MM-DD, UTC expiry")
    parser.add_argument("--demo", action="store_true", help="Restricts the clinician to built-in fictional reports.")
    args = parser.parse_args()
    try:
        with installation_lock(store.DATA), store.connect() as db:
            row = db.execute("SELECT id FROM users WHERE username=?", (args.username.lower(),)).fetchone()
            if not row:
                raise ValueError("The account must already exist. No account or credential is created implicitly.")
            if args.action == "revoke-clinician":
                db.execute("UPDATE clinicians SET active=0 WHERE user_id=?", (row[0],))
                db.execute("UPDATE schedules SET status='suspended',reason='Clinician authorization revoked.' WHERE clinician_id=? AND status IN ('requested','approved')", (row[0],))
            else:
                if not all([args.name, args.registration, args.verified_by, args.evidence, args.valid_until]):
                    raise ValueError("Name, registration, verifier, evidence reference and expiry are required.")
                expiry = datetime.fromisoformat(args.valid_until).replace(tzinfo=timezone.utc)
                if expiry <= datetime.now(timezone.utc):
                    raise ValueError("The credential expiry must be in the future.")
                db.execute("UPDATE schedules SET status='suspended',reason='Clinician credentials were replaced. Request a fresh review.' WHERE clinician_id=? AND status IN ('requested','approved')", (row[0],))
                db.execute("""INSERT INTO clinicians VALUES (?,?,?,?,?,?,1,?) ON CONFLICT(user_id) DO UPDATE SET
                    display_name=excluded.display_name,registration=excluded.registration,verified_by=excluded.verified_by,
                    evidence=excluded.evidence,valid_until=excluded.valid_until,active=1,demo=excluded.demo""",
                    (row[0], args.name, args.registration, args.verified_by, args.evidence, expiry.isoformat(), int(args.demo)))
        print("Clinician authorization updated. This command records the administrator's verification; it cannot verify a license itself.")
    except (ValueError, OSError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
