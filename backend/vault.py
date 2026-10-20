import base64
import ctypes
import os
import secrets
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"ACVAULT\x01"
DPAPI = b"ACDPAPI\x01"
DATABASE_LOCK = threading.RLock()


def windows_protect(content, decrypt=False):
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = (ctypes.c_ubyte * len(content)).from_buffer_copy(content)
    source = Blob(len(content), buffer)
    output = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    operation = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    operation.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                          ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    operation.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise OSError(ctypes.get_last_error(), "Windows could not unlock the local installation key.")
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel.LocalFree(output.data)


def atomic_write(path, content):
    if path.is_symlink():
        raise ValueError("Vault files must not be symbolic links.")
    descriptor, name = tempfile.mkstemp(prefix=".vault-write-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def write_private(path, content):
    atomic_write(path, DPAPI + windows_protect(content) if os.name == "nt" else content)
    if os.name != "nt":
        path.chmod(0o600)


def read_private(path):
    content = path.read_bytes()
    if content.startswith(DPAPI):
        if os.name != "nt":
            raise ValueError("This key is bound to its Windows user. Use an encrypted installation backup to migrate.")
        return windows_protect(content[len(DPAPI):], decrypt=True)
    return content


def enabled(directory):
    return (directory / ".vault-enabled").is_file()


def key(directory):
    configured = os.environ.get("AFTERCARE_VAULT_KEY")
    if configured:
        try:
            content = base64.b64decode(configured, validate=True)
        except ValueError:
            raise ValueError("AFTERCARE_VAULT_KEY must be a base64-encoded 32-byte key.")
    else:
        path = directory / ".vault-key"
        if not path.is_file():
            raise ValueError("The vault key is missing. Restore an encrypted backup; a replacement key cannot recover this installation.")
        content = read_private(path)
    if len(content) != 32:
        raise ValueError("The vault key must contain exactly 32 bytes.")
    return content


def read(path, allow_plain=False):
    content = path.read_bytes()
    if not content.startswith(MAGIC):
        if enabled(path.parent) and not allow_plain:
            raise ValueError("An unencrypted file appeared in the vault. Restore a validated backup.")
        return content
    nonce = content[len(MAGIC):len(MAGIC) + 12]
    return AESGCM(key(path.parent)).decrypt(nonce, content[len(MAGIC) + 12:], MAGIC + path.name.encode())


def write(path, content):
    if not enabled(path.parent):
        atomic_write(path, content)
        return
    nonce = secrets.token_bytes(12)
    cipher = AESGCM(key(path.parent))
    encrypted = cipher.encrypt(nonce, content, MAGIC + path.name.encode())
    if cipher.decrypt(nonce, encrypted, MAGIC + path.name.encode()) != content:
        raise ValueError("Vault verification failed; the existing file was retained.")
    atomic_write(path, MAGIC + nonce + encrypted)


@contextmanager
def readable(path):
    content = read(path)
    if not path.read_bytes().startswith(MAGIC):
        yield path
        return
    with tempfile.TemporaryDirectory(prefix="aftercare-reader-") as temporary:
        output = Path(temporary) / path.name
        output.write_bytes(content)
        yield output


def source_name(report):
    name = report["file"]
    if name is None:
        if report.get("kind") != "manual" or report.get("pages") or not report.get("fields") or any(field.get("source") is not None or field.get("origin") != "manual" for field in report["fields"]):
            raise ValueError("Only manually entered records can have no original document.")
    elif not isinstance(name, str) or not name:
        raise ValueError("Invalid report source name.")
    return name


def initialize(directory):
    import json
    import sqlite3
    from contextlib import closing

    with DATABASE_LOCK:
        if not enabled(directory):
            if not os.environ.get("AFTERCARE_VAULT_KEY") and not (directory / ".vault-key").exists():
                write_private(directory / ".vault-key", secrets.token_bytes(32))
            key(directory)
            atomic_write(directory / ".vault-enabled", b"migrating")
        database = directory / "aftercare.db"
        if not database.exists():
            atomic_write(directory / ".vault-enabled", b"1")
            return
        migrating = (directory / ".vault-enabled").read_bytes() == b"migrating"
        raw = read(database, allow_plain=migrating)
        with closing(sqlite3.connect(":memory:")) as db:
            db.deserialize(raw)
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("The database integrity check failed. No files were migrated.")
            names = []
            for row in db.execute("SELECT payload FROM reports"):
                name = source_name(json.loads(row[0]))
                if name is not None:
                    names.append(name)
        for tomb in directory.glob(".delete-*"):
            original_name = tomb.name[len(".delete-"):]
            target = directory / original_name
            if tomb.is_symlink() or target.is_symlink() or target.resolve().parent != directory.resolve():
                raise ValueError("Unsafe interrupted deletion path.")
            if original_name in names and not target.exists():
                tomb.replace(target)
            elif original_name not in names:
                tomb.unlink()
        for name in names:
            path = directory / name
            if Path(name).name != name or path.resolve().parent != directory.resolve() or path.is_symlink():
                raise ValueError("A report has an unsafe source path.")
            if not path.is_file():
                raise ValueError("A report source is missing. Restore it before upgrading the installation.")
        # Each replacement is authenticated and atomic; an interrupted migration resumes on startup.
        for name in names:
            path = directory / name
            content = read(path, allow_plain=migrating)
            if not path.read_bytes().startswith(MAGIC):
                write(path, content)
        if not database.read_bytes().startswith(MAGIC):
            write(database, raw)
        atomic_write(directory / ".vault-enabled", b"1")
