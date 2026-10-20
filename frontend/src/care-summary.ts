import type { Activity, CareField, Report, Visit } from "./api";

export function careSummary(
  report: Report | null,
  activity: Activity,
  today: string,
) {
  const fields = report?.fields || [];
  const pending = fields.filter((field) => field.status === "pending");
  const questions = fields.filter((field) => field.status === "clarify");
  const confirmed = fields.filter((field) => field.status === "confirmed");
  const stage = !report
    ? "add-report"
    : !fields.length
      ? "empty"
      : pending.length
        ? "review"
        : !confirmed.length
          ? "no-confirmed"
          : !report.plan_saved
            ? "save-plan"
            : questions.length
              ? "questions"
              : "track";
  const visits: {
    field: CareField;
    visit?: Visit;
    kind: "recheck" | "book" | "past" | "today" | "upcoming";
  }[] = [];
  if (report) {
    for (const field of fields.filter((field) => field.group === "Visits")) {
      const visit = activity.visits.find((item) => item.field_id === field.id);
      if (
        visit &&
        (visit.source_value !== field.value || field.status !== "confirmed")
      ) {
        visits.push({ field, visit, kind: "recheck" });
      } else if (
        field.status === "confirmed" &&
        visit?.status !== "completed"
      ) {
        const kind =
          visit?.status !== "booked" || !visit.planned_date
            ? "book"
            : visit.planned_date < today
              ? "past"
              : visit.planned_date === today
                ? "today"
                : "upcoming";
        visits.push({ field, visit, kind });
      }
    }
  }
  const priority = { recheck: 0, past: 1, today: 2, book: 3, upcoming: 4 };
  visits.sort(
    (a, b) =>
      priority[a.kind] - priority[b.kind] ||
      (a.visit?.planned_date || "").localeCompare(b.visit?.planned_date || ""),
  );
  const recentToday = activity.medications.filter((entry) => {
    const date = new Date(entry.occurred_at);
    const localDay = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
    return localDay === today;
  });
  return {
    stage,
    pending,
    questions,
    confirmed,
    visits,
    taken: recentToday.filter((entry) => entry.status === "taken").length,
    skipped: recentToday.filter((entry) => entry.status === "skipped").length,
    limited: activity.medications.length >= 100,
  };
}

export function medicines(report: Report | null) {
  const groups = new Map<string, CareField[]>();
  report?.fields
    .filter((f) => f.group.startsWith("Medication") && f.status !== "rejected")
    .forEach((f) => {
      groups.set(f.group, [...(groups.get(f.group) || []), f]);
    });
  return [...groups.entries()].map(([group, fields]) => ({
    group,
    fields,
    name: fields.find((f) => f.label === "Name")?.value || group,
    strength: fields.find((f) => f.label === "Strength")?.value,
    frequency: fields.find((f) => f.label === "Frequency")?.value,
    reviewed:
      report!.fields
        .filter((f) => f.group === group)
        .every((f) => f.status === "confirmed") &&
      fields.some((f) => f.label === "Name" && f.value.trim()) &&
      new Set(fields.map((f) => f.label)).size === fields.length,
  }));
}

export function savedMedicines(reports: Report[]) {
  return reports.flatMap((report) =>
    medicines(report).map((medicine) => ({
      report,
      medicine,
      key: `${report.id}:${medicine.group}`,
    })),
  );
}
