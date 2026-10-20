import assert from "node:assert/strict";
import test from "node:test";
import { careSummary, savedMedicines } from "../src/care-summary.ts";

const emptyActivity = { medications: [], visits: [] };
const field = (changes = {}) => ({
  id: "instruction",
  group: "Visits",
  label: "Follow-up",
  value: "Visit in one week",
  status: "confirmed",
  source: { page: 0, text: "Visit in one week", boxes: [[1, 2, 3, 4]] },
  ...changes,
});
const report = (fields, plan_saved = true) => ({
  id: "report",
  fields,
  plan_saved,
});
const today = "2026-10-18";

test("review and missing extraction cannot be presented as ready to track", () => {
  assert.equal(careSummary(null, emptyActivity, today).stage, "add-report");
  assert.equal(careSummary(report([]), emptyActivity, today).stage, "empty");
  assert.equal(
    careSummary(report([field({ status: "pending" })]), emptyActivity, today)
      .stage,
    "review",
  );
  assert.equal(
    careSummary(report([field({ status: "rejected" })]), emptyActivity, today)
      .stage,
    "no-confirmed",
  );
  assert.equal(
    careSummary(report([field()], false), emptyActivity, today).stage,
    "save-plan",
  );
  assert.equal(
    careSummary(report([field()]), emptyActivity, today).stage,
    "track",
  );
});

test("clarification retains evidence and does not count excluded fields as reviewed instructions", () => {
  const question = field({ id: "question", status: "clarify" });
  const summary = careSummary(
    report([field(), question, field({ id: "excluded", status: "rejected" })]),
    emptyActivity,
    today,
  );
  assert.equal(summary.stage, "questions");
  assert.deepEqual(summary.questions, [question]);
  assert.equal(summary.confirmed.length, 1);
  assert.equal(summary.questions[0].source.text, question.source.text);
});

test("only explicit user bookings create dated visit tasks", () => {
  const source = field({ value: "Follow-up 2026-10-18" });
  const result = careSummary(report([source]), emptyActivity, today);
  assert.equal(result.visits[0].kind, "book");
  assert.equal(result.visits[0].visit, undefined);
  for (const [date, kind] of [
    ["2026-10-17", "past"],
    [today, "today"],
    ["2026-10-19", "upcoming"],
  ]) {
    const activity = {
      medications: [],
      visits: [
        {
          field_id: source.id,
          source_value: source.value,
          status: "booked",
          planned_date: date,
        },
      ],
    };
    assert.equal(
      careSummary(report([source]), activity, today).visits[0].kind,
      kind,
    );
    assert.equal(activity.visits[0].status, "booked");
  }
});

test("changed or excluded visit evidence requires rechecking even after completion", () => {
  const source = field();
  const activity = {
    medications: [],
    visits: [
      { field_id: source.id, source_value: source.value, status: "completed" },
    ],
  };
  assert.deepEqual(careSummary(report([source]), activity, today).visits, []);
  for (const change of [
    { value: "Changed instruction" },
    { status: "clarify" },
    { status: "rejected" },
  ]) {
    const task = careSummary(report([field(change)], false), activity, today)
      .visits[0];
    assert.equal(task.kind, "recheck");
    assert.equal(task.visit.source_value, source.value);
  }
  assert.deepEqual(careSummary(report([]), activity, today).visits, []);
});

test("unreviewed visits cannot appear as unbooked care tasks", () => {
  for (const status of ["pending", "clarify", "rejected"]) {
    assert.deepEqual(
      careSummary(report([field({ status })]), emptyActivity, today).visits,
      [],
    );
  }
});

test("medication activity is counted by local date without inferring scheduled doses", () => {
  const localNoon = new Date(2026, 9, 18, 12).toISOString();
  const yesterday = new Date(2026, 9, 17, 12).toISOString();
  const medications = [
    { status: "taken", occurred_at: localNoon },
    { status: "skipped", occurred_at: localNoon },
    { status: "taken", occurred_at: yesterday },
  ];
  const summary = careSummary(
    report([
      field({
        group: "Medication 1",
        label: "Frequency",
        value: "Every 6 hours",
      }),
    ]),
    { medications, visits: [] },
    today,
  );
  assert.equal(summary.taken, 1);
  assert.equal(summary.skipped, 1);
  assert.equal(summary.limited, false);
  assert.equal(
    careSummary(
      report([field()]),
      { medications: Array(100).fill(medications[0]), visits: [] },
      today,
    ).limited,
    true,
  );
});

test("saved medicines retain separate source identities across uploads and manual entries", () => {
  const medication = (value) =>
    field({ group: "Medication 1", label: "Name", value });
  const uploaded = {
    ...report([medication("Original medicine")]),
    id: "upload",
    name: "Prescription",
  };
  const manual = {
    ...report([medication("Added medicine")]),
    id: "manual",
    kind: "manual",
  };
  const added = {
    ...report([medication("New prescription medicine")]),
    id: "second-upload",
  };
  const records = savedMedicines([uploaded, manual, added]);
  assert.deepEqual(
    records.map((item) => [item.key, item.medicine.name]),
    [
      ["upload:Medication 1", "Original medicine"],
      ["manual:Medication 1", "Added medicine"],
      ["second-upload:Medication 1", "New prescription medicine"],
    ],
  );
  assert.equal(records[0].report, uploaded);
  assert.equal(records[1].report, manual);
  assert.deepEqual(
    savedMedicines([uploaded]).map((item) => item.medicine.name),
    ["Original medicine"],
  );
});
