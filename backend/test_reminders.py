import base64
import json
from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from . import reminders, schedules, store
from .test_schedules import approve, doctor, requested
from .test_tracking import reviewed_report


def subscription(endpoint="https://fcm.googleapis.com/fcm/send/fictional"):
    public = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return {"endpoint": endpoint, "keys": {"auth": base64.urlsafe_b64encode(b"0123456789abcdef").decode(), "p256dh": base64.urlsafe_b64encode(public).decode()}}


def test_push_requires_configuration_and_rejects_arbitrary_endpoints(client, monkeypatch):
    assert client.get("/api/push/settings").json()["configured"] is False
    assert client.post("/api/push/devices", json=subscription()).status_code == 409
    monkeypatch.setenv("AFTERCARE_PUSH_SUBJECT", "mailto:demo@example.org")
    assert client.get("/api/push/settings").json()["public_key"]
    for endpoint in ["http://127.0.0.1:11434/api", "https://localhost/test", "https://fcm.googleapis.com.evil.test/push", "https://fcm.googleapis.com:444/push", "https://user@fcm.googleapis.com/push"]:
        assert client.post("/api/push/devices", json=subscription(endpoint)).status_code == 422
    assert client.post("/api/push/devices", json=subscription()).status_code == 200


def test_notifications_recheck_approval_access_completion_and_snooze(client, reviewed_report, doctor, monkeypatch):
    fixed = datetime.now(timezone.utc).replace(hour=0, minute=5, second=0, microsecond=0)
    monkeypatch.setattr(schedules, "now_utc", lambda: fixed)
    monkeypatch.setattr(reminders, "now_utc", lambda: fixed)
    monkeypatch.setenv("AFTERCARE_PUSH_SUBJECT", "mailto:demo@example.org")
    url, schedule = requested(client, reviewed_report, doctor)
    device = client.post("/api/push/devices", json=subscription()).json()
    sent = []
    monkeypatch.setattr(reminders, "send_push", lambda data, tag: sent.append((data, tag)))
    reminders.deliver_pending()
    assert sent == []
    approve(doctor, schedule)
    due = client.get("/api/reminders").json()[0]
    assert due["alerting"]
    reminders.deliver_pending(); reminders.deliver_pending()
    assert len(sent) == 1
    assert "Amoxicillin" not in json.dumps(sent)
    assert doctor[0].get("/api/reminders").json() == []
    action = {"due_at": due["due_at"], "action": "snooze"}
    client.post(url + f"/{schedule['id']}/dose", json=action)
    reminders.deliver_pending()
    assert len(sent) == 1
    later = fixed.replace(minute=16)
    monkeypatch.setattr(schedules, "now_utc", lambda: later)
    monkeypatch.setattr(reminders, "now_utc", lambda: later)
    reminders.deliver_pending()
    assert len(sent) == 2
    client.post(url + f"/{schedule['id']}/dose", json={**action, "action": "taken"})
    reminders.deliver_pending()
    assert len(sent) == 2
    client.post(url + f"/{schedule['id']}/stop")
    assert client.get("/api/reminders").json() == []
    assert client.delete(f"/api/push/devices/{device['id']}").status_code == 200


def test_retry_is_bounded_and_failed_provider_does_not_destroy_dose(client, reviewed_report, doctor, monkeypatch):
    fixed = datetime.now(timezone.utc).replace(hour=0, minute=5, second=0, microsecond=0)
    monkeypatch.setattr(schedules, "now_utc", lambda: fixed)
    monkeypatch.setattr(reminders, "now_utc", lambda: fixed)
    monkeypatch.setenv("AFTERCARE_PUSH_SUBJECT", "mailto:demo@example.org")
    _, schedule = requested(client, reviewed_report, doctor)
    approve(doctor, schedule)
    client.post("/api/push/devices", json=subscription())
    def fail(*args):
        raise TimeoutError()
    monkeypatch.setattr(reminders, "send_push", fail)
    for _ in range(5):
        reminders.deliver_pending()
    with store.connect() as db:
        assert db.execute("SELECT attempts,status FROM push_deliveries").fetchone()["attempts"] == 3
        assert not db.execute("SELECT 1 FROM scheduled_doses").fetchone()
    assert client.get("/api/reminders").json()[0]["alerting"]


def test_real_webpush_encryption_uses_generic_payload_without_network(client, monkeypatch):
    import http_ece
    import requests
    import pywebpush
    monkeypatch.setenv("AFTERCARE_PUSH_SUBJECT", "https://localhost")
    private = ec.generate_private_key(ec.SECP256R1())
    public = private.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    auth = b"0123456789abcdef"
    value = {"endpoint": "https://fcm.googleapis.com/fcm/send/fictional", "keys": {
        "auth": base64.urlsafe_b64encode(auth).decode(), "p256dh": base64.urlsafe_b64encode(public).decode()}}
    captured = {}
    class Transport:
        max_redirects = None
        def post(self, url, **kwargs):
            captured.update(kwargs)
            response = requests.Response()
            response.status_code = 201
            response._content = b""
            return response
    transport = Transport()
    monkeypatch.setattr(requests, "Session", lambda: transport)
    reminders.send_push(value, "opaque-schedule:opaque-dose")
    assert transport.max_redirects == 0
    assert captured["timeout"] == 10
    decoded = http_ece.decrypt(captured["data"], private_key=private, auth_secret=auth, version="aes128gcm")
    assert json.loads(decoded) == {"tag": "opaque-schedule:opaque-dose"}
    assert captured["headers"]["ttl"] == "60"
