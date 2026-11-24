import assert from "node:assert/strict";
import { test } from "node:test";
import {
  mergeServerSchedules,
  phoneSchedules,
  phoneToday,
  queueDose,
} from "../src/phone-state.ts";

const now = Date.parse("2026-10-28T10:00:00Z");
function fixture() {
  const dose = {
    due_at: "2026-10-28T08:00:00+00:00",
    status: "pending",
    note: "",
    actor_id: null,
    recorded_at: null,
    snoozed_until: null,
  };
  const schedule = {
    id: "s1",
    report_id: "r1",
    status: "active",
    fingerprint: "a".repeat(64),
    payload: { name: "Example medicine", dose: "1 tablet", timezone: "UTC" },
    doses: [dose],
    offline_doses: [dose, { ...dose, due_at: "2026-10-29T08:00:00+00:00" }],
    history: [],
  };
  return {
    version: 1,
    account: { id: "u1", username: "fictional" },
    workspace: {
      patients: [{ id: "p1", access_role: "owner", episodes: [{ id: "e1" }] }],
    },
    reports: [{ id: "r1", episode_id: "e1" }],
    schedules: { r1: [schedule] },
    synced_at: "2026-10-28T09:00:00Z",
    valid_until: "2026-11-04T09:00:00Z",
  };
}
const action = { due_at: "2026-10-28T08:00:00+00:00", action: "taken" };

test("offline records retain the source fingerprint, actor and original server state", () => {
  const snapshot = fixture();
  const entry = queueDose(snapshot, [], "r1", "s1", action, "first", now);
  assert.equal(entry.body.offline.fingerprint, "a".repeat(64));
  assert.equal(entry.body.offline.expected_recorded_at, null);
  assert.equal(phoneToday(snapshot, "p1", [entry], now)[0].status, "taken");
  assert.equal(phoneToday(snapshot, "p1", [entry], now)[0].actor_id, "u1");
  assert.equal(snapshot.schedules.r1[0].offline_doses[0].status, "pending");
});

test("offline recording rejects unknown, future, shared and expired plans", () => {
  for (const change of [
    (value) => {
      value.schedules.r1[0].status = "suspended";
    },
    (value) => {
      value.workspace.patients[0].access_role = "viewer";
    },
    (value) => {
      value.valid_until = "2026-10-27T09:00:00Z";
    },
  ]) {
    const snapshot = fixture();
    change(snapshot);
    assert.throws(() => queueDose(snapshot, [], "r1", "s1", action, "id", now));
  }
  assert.throws(() =>
    queueDose(
      fixture(),
      [],
      "r1",
      "s1",
      { ...action, due_at: "2026-10-29T08:00:00+00:00" },
      "id",
      now,
    ),
  );
  assert.throws(() =>
    queueDose(fixture(), [], "r1", "wrong", action, "id", now),
  );
  assert.throws(() => phoneToday(fixture(), "shared-person", [], now));
});

test("taken then undo keeps a causal request chain and rejects duplicate actions", () => {
  const snapshot = fixture();
  const first = queueDose(snapshot, [], "r1", "s1", action, "first", now);
  assert.throws(() =>
    queueDose(snapshot, [first], "r1", "s1", action, "duplicate", now),
  );
  const undo = queueDose(
    snapshot,
    [first],
    "r1",
    "s1",
    { ...action, action: "undo" },
    "second",
    now + 1000,
  );
  assert.equal(undo.body.offline.after_request_id, "first");
  assert.equal(
    phoneToday(snapshot, "p1", [first, undo], now)[0].status,
    "pending",
  );
  first.conflict = "Changed elsewhere";
  assert.throws(() =>
    queueDose(snapshot, [first], "r1", "s1", action, "third", now),
  );
});

test("acknowledging sync preserves completed records across restart and future dates", () => {
  const snapshot = fixture();
  const incoming = {
    ...snapshot.schedules.r1[0],
    doses: [
      {
        ...snapshot.schedules.r1[0].doses[0],
        status: "taken",
        recorded_at: "2026-10-28T10:01:00Z",
      },
    ],
  };
  mergeServerSchedules(snapshot, "r1", [incoming]);
  const restarted = JSON.parse(JSON.stringify(snapshot));
  assert.equal(phoneToday(restarted, "p1", [], now)[0].status, "taken");
  assert.equal(
    phoneSchedules(restarted, "r1", [], "2026-10-29", now)[0].doses[0].status,
    "pending",
  );
  mergeServerSchedules(restarted, "r1", [{ ...incoming, status: "stopped" }]);
  assert.deepEqual(phoneToday(restarted, "p1", [], now), []);
});
