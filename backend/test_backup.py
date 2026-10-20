import io
import json
import sqlite3
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from . import backup, store, vault
from .test_sharing import caregiver, event, invite, reviewed

PASSPHRASE = "fictional-backup-passphrase-2026"


def test_encrypted_restore_preserves_evidence_and_disables_old_access(client, caregiver, tmp_path):
    report = reviewed(client)
    prefix = f"/api/reports/{report['id']}"
    original = client.get(prefix + "/file").content
    history = client.get(prefix + "/history").json()
    logged = client.post(prefix + "/medications/log", json=event()).json()["medications"][0]
    client.post(f"{prefix}/medications/log/{logged['id']}/undo")
    client.post("/api/auth/recovery-code", json={"current_password": "fictional-password-123"})
    _, invitation = invite(client)
    caregiver.post(f"/api/care/invitations/{invitation}/respond", json={"action": "accept"})
    source = tmp_path / "copy.acb"
    backup.create_backup(store.DATA, source, PASSPHRASE)
    assert b"Willowbrook" not in source.read_bytes()
    restored = tmp_path / "restored"
    backup.restore_backup(source, restored, PASSPHRASE)
    assert caregiver.get(prefix).status_code == 200
    with sqlite3.connect(":memory:") as db:
        db.deserialize(vault.read(restored / "aftercare.db"))
        db.row_factory = sqlite3.Row
        payload = json.loads(db.execute("SELECT payload FROM reports WHERE id=?", (report["id"],)).fetchone()[0])
        assert payload["plan_saved"] and vault.read(restored / payload["file"]) == original
        assert [dict(row) for row in db.execute("SELECT * FROM reviews WHERE report_id=? ORDER BY id DESC", (report["id"],))] == history
        assert db.execute("SELECT voided_at FROM medication_entries WHERE id=?", (logged["id"],)).fetchone()[0]
        assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM recovery_codes").fetchone()[0] == 0
        assert db.execute("SELECT status FROM caregiver_access WHERE id=?", (invitation,)).fetchone()[0] == "revoked"


@pytest.mark.parametrize("tampered", [False, True])
def test_wrong_password_or_tampering_cannot_write_restored_files(client, tmp_path, tampered):
    client.post("/api/reports/sample")
    path = tmp_path / "copy.acb"
    backup.create_backup(store.DATA, path, PASSPHRASE)
    if tampered:
        content = bytearray(path.read_bytes())
        content[-1] ^= 1
        path.write_bytes(content)
    target = tmp_path / "rejected"
    with pytest.raises(ValueError, match="incorrect or.*changed"):
        backup.restore_backup(path, target, PASSPHRASE if tampered else "wrong-passphrase-123")
    assert not target.exists()


def test_restoration_never_overwrites_an_existing_installation(client, tmp_path):
    path = tmp_path / "copy.acb"
    backup.create_backup(store.DATA, path, PASSPHRASE)
    target = tmp_path / "existing"
    target.mkdir()
    sentinel = target / "keep.txt"
    sentinel.write_text("Keep existing data")
    with pytest.raises(ValueError, match="new empty folder"):
        backup.restore_backup(path, target, PASSPHRASE)
    assert sentinel.read_text() == "Keep existing data"


def test_missing_original_refuses_a_partial_backup(client, tmp_path):
    report = client.post("/api/reports/sample").json()
    (store.DATA / report["file"]).unlink()
    output = tmp_path / "partial.acb"
    with pytest.raises(ValueError, match="source is missing"):
        backup.create_backup(store.DATA, output, PASSPHRASE)
    assert not output.exists()


def test_backup_refuses_a_running_installation(client, tmp_path):
    with backup.installation_lock(store.DATA):
        with pytest.raises(ValueError, match="Stop AfterCare"):
            backup.create_backup(store.DATA, tmp_path / "locked.acb", PASSPHRASE)


def test_archive_path_traversal_is_rejected_before_installing(client, tmp_path):
    content = io.BytesIO()
    with ZipFile(content, "w", ZIP_DEFLATED) as bundle:
        bundle.writestr("../outside.txt", "not allowed")
        bundle.writestr("aftercare.db", "invalid")
        bundle.writestr("manifest.json", json.dumps({"format": "aftercare-installation", "version": 1, "files": {"../outside.txt": "bad", "aftercare.db": "bad"}}))
    path = tmp_path / "unsafe.acb"
    path.write_bytes(backup.encrypt(content.getvalue(), PASSPHRASE))
    with pytest.raises(ValueError):
        backup.restore_backup(path, tmp_path / "safe", PASSPHRASE)
    assert not (tmp_path / "outside.txt").exists()
    assert not (tmp_path / "safe" / "aftercare.db").exists()
