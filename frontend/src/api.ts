export type CareField = {
  id: string;
  group: string;
  label: string;
  value: string;
  status: "pending" | "confirmed" | "rejected" | "clarify";
  origin?: "manual";
  source: { page: number; text: string; boxes: number[][] } | null;
};

export type Report = {
  id: string;
  kind?: "manual";
  entry_type?: "visit";
  revision?: string;
  episode_id: string;
  name: string;
  engine: string;
  sample: boolean;
  created: string;
  fields: CareField[];
  pages: {
    number: number;
    width: number;
    height: number;
    method?: "pdf_text" | "ocr";
  }[];
  plan_saved: boolean;
  warnings: string[];
};

export type ArchivedReport = Pick<Report, "id" | "name" | "episode_id"> & {
  archived_at: string;
};

export type MedicationLog = {
  id: string;
  medication_group: string;
  status: "taken" | "skipped";
  occurred_at: string;
  note: string;
  snapshot: Record<string, string>;
  actor_id: string | null;
  actor_name: string | null;
};

export type Visit = {
  field_id: string;
  status: "planned" | "booked" | "completed";
  planned_date: string | null;
  note: string;
  source_value: string;
  actor_name: string | null;
};

export type VisitItem = {
  report_id: string;
  report_name: string;
  plan_saved: boolean;
  field: CareField;
  visit: Visit | null;
};

export type Activity = { medications: MedicationLog[]; visits: Visit[] };
export type Clinician = {
  user_id: string;
  display_name: string;
  registration: string;
  demo: boolean;
  valid_until: string;
};
export type Schedule = {
  id: string;
  report_id: string;
  status:
    "active" | "requested" | "approved" | "rejected" | "stopped" | "suspended";
  authority?: "personal" | "clinical";
  fingerprint: string;
  clinician_name: string;
  demo: boolean;
  reason: string;
  decision_note: string | null;
  decision_at: string | null;
  payload: {
    group: string;
    name: string;
    strength?: string;
    dose: string;
    times: string[];
    start: string;
    end: string;
    timezone: string;
    source: CareField[];
  };
  history?: {
    due_at: string;
    status: string;
    note: string;
    actor_name: string | null;
    recorded_at: string;
  }[];
  doses: {
    due_at: string;
    status: "pending" | "taken" | "skipped";
    note: string;
    actor_id: string | null;
    recorded_at: string | null;
    snoozed_until: string | null;
  }[];
};
export type ClinicalQueue = {
  identity: (Clinician & { verified_by: string; evidence: string }) | null;
  requests: { schedule: Schedule; report: Report }[];
};
export type Reminder = {
  kind?: "dose" | "care";
  schedule_id: string;
  report_id: string;
  name: string;
  dose: string;
  due_at: string;
  alert_at: string;
  alerting: boolean;
  demo: boolean;
};
export type Account = { id: string; username: string };
export type Episode = {
  id: string;
  patient_id: string;
  title: string;
  started: string;
};
export type Contact = {
  id: string;
  name: string;
  role: string;
  phone: string;
  note: string;
};
export type Patient = {
  id: string;
  name: string;
  episodes: Episode[];
  contacts: Contact[];
  access_role: "owner" | "viewer" | "recorder";
  owner_username: string;
  sharing: {
    id: string;
    username: string;
    role: "viewer" | "recorder";
    status: "pending" | "active" | "revoked" | "declined" | "expired";
    expires_at: string;
    alerts: {
      taken: boolean;
      skipped: boolean;
      unconfirmed: boolean;
      delay_minutes: number;
    };
  }[];
};
export type Workspace = {
  patients: Patient[];
  personal?: { patient_id: string; episode_id: string };
  legacy_count: number;
  invitations: {
    id: string;
    patient_name: string;
    owner_username: string;
    role: "viewer" | "recorder";
    expires_at: string;
  }[];
};
export type CareAudit = {
  id: number;
  actor_name: string;
  recipient_name: string | null;
  action: string;
  detail: string;
  created_at: string;
};

export function jsonRequest(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

async function request(path: string, options?: RequestInit) {
  const response = await fetch(`/api${path}`, options);
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith("/auth/"))
      window.dispatchEvent(new Event("aftercare-signed-out"));
    const error = await response.json().catch(() => ({}));
    throw new Error(
      typeof error.detail === "string"
        ? error.detail
        : Array.isArray(error.detail)
          ? error.detail
              .map((item: { msg: string }) =>
                item.msg.replace(/^Value error, /, ""),
              )
              .join(" ")
          : "That request could not be completed. Please try again.",
    );
  }
  return response;
}

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  return (await request(path, options)).json();
}

export async function downloadReport(id: string) {
  const response = await request(`/reports/${id}/export`);
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = "aftercare-report.zip";
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function updateField(
  reportId: string,
  field: CareField,
  status: CareField["status"],
  value: string,
) {
  return api<Report>(`/reports/${reportId}/fields/${field.id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status, value }),
  });
}

export type Routine = {
  wake: string;
  breakfast: string;
  lunch: string;
  dinner: string;
  sleep: string;
  timezone: string;
};
export type Timing = {
  duration_days?: number | null;
  revision: string;
  dose: string;
  times: string[];
  start: string;
  end: string;
  timezone: string;
  explanation: string;
  blocked: string[];
  can_schedule: boolean;
};
export type MedicineInfo = {
  name: string;
  matched: boolean;
  facts: string[];
  source_url: string | null;
  notice: string;
  reason: string | null;
  reason_origin: string | null;
  reason_source: CareField["source"];
  context: {
    id: string;
    label: string;
    value: string;
    source: CareField["source"];
    origin: string;
    status: CareField["status"];
  }[];
  context_notice: string | null;
  method: string;
};
export type TodayDose = Schedule["doses"][number] & {
  schedule_id: string;
  report_id: string;
  name: string;
  strength?: string;
  dose: string;
  timezone: string;
};
export type CareNotification = {
  patient_id: string;
  id: string;
  report_id: string;
  patient_name: string;
  kind: string;
  body: string;
  created_at: string;
  read_at: string | null;
};

export type AlertPreferences = {
  taken: boolean;
  skipped: boolean;
  unconfirmed: boolean;
  delay_minutes: number;
};
