import type {
  Account,
  Activity,
  Report,
  Schedule,
  TodayDose,
  Workspace,
} from "./api";

export type PhoneSchedule = Schedule & { offline_doses: Schedule["doses"] };
export type PhoneSnapshot = {
  version: 1;
  account: Account;
  workspace: Workspace;
  reports: Report[];
  schedules: Record<string, PhoneSchedule[]>;
  activities: Record<string, Activity>;
  synced_at: string;
  valid_until: string;
};
export type PendingDose = {
  reportId: string;
  scheduleId: string;
  medicineName: string;
  dose: string;
  body: {
    due_at: string;
    action: "taken" | "skipped" | "snooze" | "undo";
    note: string;
    offline: {
      request_id: string;
      fingerprint: string;
      expected_recorded_at: string | null;
      after_request_id: string | null;
      recorded_at: string;
    };
  };
  conflict?: string;
};

export function mergeServerSchedules(
  snapshot: PhoneSnapshot,
  reportId: string,
  incoming: Schedule[],
) {
  snapshot.schedules[reportId] = incoming.map((schedule) => {
    const previous = snapshot.schedules[reportId]?.find(
      (value) => value.id === schedule.id,
    );
    const records = [...schedule.doses, ...(schedule.history || [])];
    return {
      ...schedule,
      offline_doses: (previous?.offline_doses || schedule.doses).map((dose) => {
        const record = records.find((value) => value.due_at === dose.due_at);
        if (!record || !["pending", "taken", "skipped"].includes(record.status))
          return dose;
        return {
          ...dose,
          ...record,
          status: record.status as typeof dose.status,
        };
      }),
    };
  });
}

export function localDate(value: string | number, timezone: string) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(value));
}

export function phoneSchedules(
  snapshot: PhoneSnapshot,
  reportId: string,
  queue: PendingDose[],
  day?: string,
  now = Date.now(),
) {
  return (snapshot.schedules[reportId] || []).map((schedule) => {
    const all = schedule.offline_doses.map((original) => {
      const value = { ...original };
      for (const event of queue.filter(
        (entry) =>
          !entry.conflict &&
          entry.scheduleId === schedule.id &&
          entry.body.due_at === original.due_at,
      )) {
        const { action, note, offline } = event.body;
        value.status =
          action === "taken" || action === "skipped" ? action : "pending";
        value.note = note;
        value.actor_id = snapshot.account.id;
        value.recorded_at = offline.recorded_at;
        value.snoozed_until =
          action === "snooze"
            ? new Date(Date.parse(offline.recorded_at) + 600000).toISOString()
            : null;
      }
      return value;
    });
    return {
      ...schedule,
      offline_doses: all,
      doses: all.filter(
        (dose) =>
          localDate(dose.due_at, schedule.payload.timezone) ===
          (day || localDate(now, schedule.payload.timezone)),
      ),
    };
  });
}

export function phoneToday(
  snapshot: PhoneSnapshot,
  patientId: string,
  queue: PendingDose[],
  now = Date.now(),
): TodayDose[] {
  const patient = snapshot.workspace.patients.find(
    (value) => value.id === patientId && value.access_role === "owner",
  );
  if (!patient)
    throw new Error("Shared care needs a connection to check current access.");
  const episodes = new Set(patient.episodes.map((episode) => episode.id));
  return snapshot.reports
    .filter((report) => episodes.has(report.episode_id))
    .flatMap((report) =>
      phoneSchedules(snapshot, report.id, queue, undefined, now)
        .filter((schedule) => ["active", "approved"].includes(schedule.status))
        .flatMap((schedule) =>
          schedule.doses.map((dose) => ({
            ...dose,
            report_id: report.id,
            schedule_id: schedule.id,
            name: schedule.payload.name,
            strength: schedule.payload.strength,
            dose: schedule.payload.dose,
            timezone: schedule.payload.timezone,
          })),
        ),
    )
    .sort((a, b) => a.due_at.localeCompare(b.due_at));
}

export function queueDose(
  snapshot: PhoneSnapshot,
  queue: PendingDose[],
  reportId: string,
  scheduleId: string,
  body: {
    due_at: string;
    action: PendingDose["body"]["action"];
    note?: string;
  },
  requestId: string,
  now = Date.now(),
): PendingDose {
  if (now >= Date.parse(snapshot.valid_until))
    throw new Error(
      "Reconnect to refresh your downloaded plans before recording doses.",
    );
  const report = snapshot.reports.find((value) => value.id === reportId);
  if (
    !snapshot.workspace.patients.some(
      (patient) =>
        patient.access_role === "owner" &&
        patient.episodes.some((episode) => episode.id === report?.episode_id),
    )
  )
    throw new Error("Shared care needs a connection to check current access.");
  const schedule = phoneSchedules(snapshot, reportId, queue).find(
    (value) => value.id === scheduleId,
  );
  const dose = schedule?.offline_doses.find(
    (value) => value.due_at === body.due_at,
  );
  if (
    !schedule ||
    !["active", "approved"].includes(schedule.status) ||
    !dose ||
    Date.parse(dose.due_at) > now
  )
    throw new Error("Choose a due dose from a downloaded, confirmed plan.");
  if (
    body.action === "undo"
      ? dose.status === "pending"
      : dose.status !== "pending"
  )
    throw new Error(
      "This dose is already recorded, or there is no completed recording to undo.",
    );
  const previous = queue
    .filter(
      (value) =>
        value.scheduleId === scheduleId && value.body.due_at === body.due_at,
    )
    .at(-1);
  if (previous?.conflict)
    throw new Error(
      "Check the sync conflict for this dose before recording again.",
    );
  return {
    reportId,
    scheduleId,
    medicineName: schedule.payload.name,
    dose: schedule.payload.dose,
    body: {
      ...body,
      note: body.note || "",
      offline: {
        request_id: requestId,
        fingerprint: schedule.fingerprint,
        expected_recorded_at: dose.recorded_at,
        after_request_id: previous?.body.offline.request_id || null,
        recorded_at: new Date(now).toISOString(),
      },
    },
  };
}
