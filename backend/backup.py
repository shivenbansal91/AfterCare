import argparse
import getpass
import hashlib
import io
import json
import os
import secrets
import sqlite3
import tempfile
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

from . import vault

MAGIC = b"AFTERCARE\x01"
LIMIT = 512 * 1024 * 1024


@contextmanager
def installation_lock(directory: Path):
    if directory.is_symlink() or (directory / ".aftercare.lock").is_symlink():
        raise ValueError("Use a real installation directory, not a symbolic link.")
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".aftercare.lock").open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ValueError("Stop AfterCare before backing up or restoring this installation.") from error
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def key(password: str, salt: bytes):
    if not 12 <= len(password) <= 256:
        raise ValueError("Use a backup passphrase of 12–256 characters.")
    return hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)


def encrypt(content: bytes, password: str):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    header = MAGIC + salt + nonce
    return header + AESGCM(key(password, salt)).encrypt(nonce, content, header)


def decrypt(content: bytes, password: str):
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if len(content) > LIMIT or len(content) < len(MAGIC) + 44 or not content.startswith(MAGIC):
        raise ValueError("This is not a supported AfterCare encrypted backup.")
    offset = len(MAGIC)
    salt, nonce = content[offset:offset + 16], content[offset + 16:offset + 28]
    try:
        return AESGCM(key(password, salt)).decrypt(nonce, content[offset + 28:], content[:offset + 28])
    except InvalidTag as error:
        raise ValueError("The backup passphrase is incorrect or the backup was changed.") from error


def source_files(db, directory: Path):
    result = []
    for (payload,) in db.execute("SELECT payload FROM reports"):
        name = vault.source_name(json.loads(payload))
        if name is None:
            continue
        path = directory / name
        if Path(name).name != name or path.resolve().parent != directory.resolve() or path.is_symlink():
            raise ValueError("A report references an unsafe source path.")
        if not path.is_file():
            raise ValueError("A report source is missing; a partial backup was not created.")
        if name in {"aftercare.db", "manifest.json", ".aftercare.lock"}:
            raise ValueError("A report references a reserved file name.")
        result.append(path)
    return list(dict.fromkeys(result))


def create_backup(directory: Path, destination: Path, password: str):
    with installation_lock(directory), tempfile.TemporaryDirectory(prefix="aftercare-backup-") as temporary:
        database = directory / "aftercare.db"
        if not database.is_file():
            raise ValueError("No AfterCare database was found in this folder.")
        snapshot = Path(temporary) / "aftercare.db"
        with closing(sqlite3.connect(":memory:")) as source, closing(sqlite3.connect(snapshot)) as target:
            source.deserialize(vault.read(database))
            source.backup(target)
        with closing(sqlite3.connect(snapshot)) as db:
            files = source_files(db, directory)
        paths = [snapshot, *files]
        if sum(path.stat().st_size for path in paths) > LIMIT - 1024 * 1024:
            raise ValueError("This backup exceeds the local 512 MB limit.")
        output = io.BytesIO()
        manifest = {"format": "aftercare-installation", "version": 1,
                    "created_at": datetime.now(timezone.utc).isoformat(), "files": {}}
        with ZipFile(output, "w", ZIP_DEFLATED) as bundle:
            for path in paths:
                content = vault.read(path) if path != snapshot else path.read_bytes()
                manifest["files"][path.name] = hashlib.sha256(content).hexdigest()
                bundle.writestr(path.name, content)
            bundle.writestr("manifest.json", json.dumps(manifest))
        encrypted = encrypt(output.getvalue(), password)
        with destination.open("xb") as handle:
            handle.write(encrypted)


def restore_backup(backup: Path, destination: Path, password: str):
    if backup.stat().st_size > LIMIT:
        raise ValueError("This backup exceeds the local 512 MB limit.")
    content = decrypt(backup.read_bytes(), password)
    with installation_lock(destination), tempfile.TemporaryDirectory(prefix="aftercare-restore-") as temporary:
        if any(path.name != ".aftercare.lock" for path in destination.iterdir()):
            raise ValueError("Restore into a new empty folder. Existing installations are never overwritten.")
        staging = Path(temporary)
        try:
            with ZipFile(io.BytesIO(content)) as bundle:
                names = bundle.namelist()
                if len(names) != len(set(names)) or len(names) > 10001:
                    raise ValueError("Invalid or duplicate backup entries.")
                if sum(item.file_size for item in bundle.infolist()) > LIMIT:
                    raise ValueError("The expanded backup exceeds the local 512 MB limit.")
                manifest = json.loads(bundle.read("manifest.json"))
                if manifest.get("format") != "aftercare-installation" or manifest.get("version") != 1:
                    raise ValueError("Unsupported backup format.")
                if set(names) != set(manifest["files"]) | {"manifest.json"} or "aftercare.db" not in names:
                    raise ValueError("The backup manifest does not match its contents.")
                for name, digest in manifest["files"].items():
                    if Path(name).name != name or "/" in name or "\\" in name or ":" in name or name in {".", "..", ".aftercare.lock"}:
                        raise ValueError("Unsafe backup entry.")
                    data = bundle.read(name)
                    if hashlib.sha256(data).hexdigest() != digest:
                        raise ValueError("A backup file failed its integrity check.")
                    (staging / name).write_bytes(data)
        except (BadZipFile, KeyError, TypeError, json.JSONDecodeError) as error:
            raise ValueError("The backup contents could not be validated.") from error
        with closing(sqlite3.connect(staging / "aftercare.db")) as db, db:
            db.execute("PRAGMA trusted_schema=OFF")
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("The backup database failed its integrity check.")
            schema = db.execute("SELECT type,sql FROM sqlite_master WHERE type IN ('view','trigger') OR upper(sql) LIKE 'CREATE VIRTUAL%'").fetchall()
            if schema:
                raise ValueError("The backup contains unsupported database objects.")
            files = source_files(db, staging)
            if set(manifest["files"]) != {"aftercare.db", *(path.name for path in files)}:
                raise ValueError("The backup contains unreferenced files.")
            db.execute("DELETE FROM sessions")
            db.execute("DELETE FROM recovery_codes")
            db.execute("DELETE FROM login_attempts")
            db.execute("UPDATE caregiver_access SET status='revoked',updated_at=? WHERE status IN ('active','pending')",
                       (datetime.now(timezone.utc).isoformat(),))
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "schedules" in tables:
                db.execute("UPDATE schedules SET status='suspended',consent=0,reason='Restored backup requires fresh consent and clinical approval.'")
                db.execute("UPDATE clinicians SET active=0")
                db.execute("DELETE FROM push_devices")
                db.execute("DELETE FROM push_deliveries")
                if "care_notifications" in tables:
                    db.execute("DELETE FROM care_notifications")
        # Only validated data reaches the new installation; no existing folder is replaced.
        copied = []
        try:
            for path in staging.iterdir():
                target = destination / path.name
                with target.open("xb") as handle:
                    copied.append(target)
                    handle.write(path.read_bytes())
        except OSError:
            for path in copied:
                path.unlink(missing_ok=True)
            raise
        vault.initialize(destination)


def main():
    parser = argparse.ArgumentParser(description="Offline encrypted backup/restore for an entire local installation.")
    parser.add_argument("action", choices=["create", "restore"])
    parser.add_argument("file", type=Path)
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    password = getpass.getpass("Backup passphrase: ")
    try:
        if args.action == "create":
            if password != getpass.getpass("Confirm passphrase: "):
                raise ValueError("The passphrases do not match.")
            create_backup(args.data_dir, args.file, password)
        else:
            restore_backup(args.file, args.data_dir, password)
        print("Backup created." if args.action == "create" else "Restored to the new folder. Sign in again and reissue recovery codes and caregiver invitations.")
    except (ValueError, OSError, sqlite3.DatabaseError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
