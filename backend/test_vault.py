import base64
import json
import secrets
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from cryptography.exceptions import InvalidTag

from . import backup, store, vault


def test_existing_source_and_entire_database_are_encrypted_without_losing_evidence(client):
    report = client.post("/api/reports/sample").json()
    original = client.get(f"/api/reports/{report['id']}/file").content
    vault.initialize(store.DATA)
    assert (store.DATA / "aftercare.db").read_bytes().startswith(vault.MAGIC)
    assert b"test-owner" not in (store.DATA / "aftercare.db").read_bytes()
    path = store.DATA / report["file"]
    assert path.read_bytes().startswith(vault.MAGIC)
    assert vault.read(path) == original
    assert client.get(f"/api/reports/{report['id']}/file").content == original
    assert client.get(f"/api/reports/{report['id']}/pages/0").status_code == 200
    field = report["fields"][0]
    assert client.patch(f"/api/reports/{report['id']}/fields/{field['id']}", json={"status": "confirmed", "value": "Corrected name"}).status_code == 200
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 1
    assert b"Corrected name" not in (store.DATA / "aftercare.db").read_bytes()
    vault.initialize(store.DATA)
    assert vault.read(path) == original


def test_vault_rejects_tampering_wrong_key_and_file_swaps(client, monkeypatch):
    client.post("/api/reports/sample")
    vault.initialize(store.DATA)
    path = store.DATA / "aftercare.db"
    original = path.read_bytes()
    plain = vault.read(path)
    path.write_bytes(plain)
    with pytest.raises(ValueError, match="unencrypted file"):
        vault.read(path)
    path.write_bytes(original)
    monkeypatch.setenv("AFTERCARE_VAULT_KEY", base64.b64encode(secrets.token_bytes(32)).decode())
    with pytest.raises(InvalidTag):
        vault.read(path)
    assert path.read_bytes() == original
    monkeypatch.delenv("AFTERCARE_VAULT_KEY")
    changed = bytearray(original); changed[-1] ^= 1
    path.write_bytes(changed)
    with pytest.raises(InvalidTag):
        vault.read(path)
    path.write_bytes(original)
    swapped = store.DATA / "swapped.db"
    swapped.write_bytes(original)
    with pytest.raises(InvalidTag):
        vault.read(swapped)


def test_encrypted_transactions_rollback_and_serialize_concurrent_writes(client):
    vault.initialize(store.DATA)
    with pytest.raises(ValueError):
        with store.connect() as db:
            db.execute("INSERT INTO users VALUES ('rollback','rollback','hash')")
            raise ValueError("abort")
    def add(number):
        with store.connect() as db:
            db.execute("INSERT INTO users VALUES (?,?,?)", (str(number), f"concurrent-{number}", "hash"))
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(add, range(12)))
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM users WHERE username LIKE 'concurrent-%'").fetchone()[0] == 12
        assert not db.execute("SELECT 1 FROM users WHERE id='rollback'").fetchone()


def test_encrypted_backup_can_migrate_to_a_new_local_key(client, tmp_path):
    report = client.post("/api/reports/sample").json()
    original = client.get(f"/api/reports/{report['id']}/file").content
    vault.initialize(store.DATA)
    source_key = vault.key(store.DATA)
    path = tmp_path / "encrypted.acb"
    backup.create_backup(store.DATA, path, "fictional-vault-backup-password")
    restored = tmp_path / "restored"
    backup.restore_backup(path, restored, "fictional-vault-backup-password")
    assert vault.key(restored) != source_key
    assert vault.read(restored / report["file"]) == original
    with sqlite3.connect(":memory:") as db:
        db.deserialize(vault.read(restored / "aftercare.db"))
        assert json.loads(db.execute("SELECT payload FROM reports").fetchone()[0])["fields"] == report["fields"]
        assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
