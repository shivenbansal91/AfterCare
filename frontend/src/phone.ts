import {
  CapacitorCookies,
  CapacitorHttp,
  registerPlugin,
} from "@capacitor/core";
import { LocalNotifications } from "@capacitor/local-notifications";
import { isPhone, serverOrigin } from "./phone-platform";
import {
  mergeServerSchedules,
  phoneSchedules,
  phoneToday,
  queueDose,
  type PendingDose,
  type PhoneSnapshot,
} from "./phone-state";

const vault = registerPlugin<{
  load(): Promise<{ value: string | null }>;
  save(options: { value: string }): Promise<void>;
  clear(): Promise<void>;
  openFile(options: {
    data: string;
    name: string;
    mime: string;
  }): Promise<void>;
}>("PhoneVault");
type PhoneState = {
  version: 1;
  origin: string;
  snapshot?: PhoneSnapshot;
  queue: PendingDose[];
  reviewedConflicts?: PendingDose[];
  enabled: boolean;
  locked: boolean;
  needsRefresh?: boolean;
};
let state: PhoneState = {
  version: 1,
  origin: "",
  queue: [],
  enabled: false,
  locked: false,
};
let initialized: Promise<void> | undefined;
let syncing: Promise<void> | undefined;
let lastError = "";
let connected = false;
let writing = Promise.resolve();
let signingOut = false;

function emit() {
  window.dispatchEvent(new Event("aftercare-phone-status"));
}
export function phoneStatus() {
  return {
    connected,
    syncing: !!syncing,
    lastSync: state.snapshot?.synced_at,
    expires: state.snapshot?.valid_until,
    pending: state.queue.filter((item) => !item.conflict).length,
    conflicts: state.queue.filter((item) => item.conflict),
    reviewedConflicts: state.reviewedConflicts || [],
    enabled: state.enabled,
    error: lastError,
    needsRefresh: !!state.needsRefresh,
  };
}
async function initialize() {
  if (!initialized)
    initialized = (async () => {
      const saved = await vault.load();
      if (saved.value) {
        const value = JSON.parse(saved.value) as PhoneState;
        if (value.version !== 1 || value.origin !== serverOrigin())
          throw new Error(
            "This phone has records from a different server. Use the original app configuration to sync them first.",
          );
        state = value;
      } else state.origin = serverOrigin();
    })();
  return initialized;
}
async function save() {
  const value = JSON.stringify(state);
  const operation = writing.then(() => vault.save({ value }));
  writing = operation.catch(() => {});
  await operation;
  emit();
}
function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export async function phoneFetch(
  path: string,
  options?: RequestInit,
): Promise<Response> {
  const headers = Object.fromEntries(new Headers(options?.headers).entries());
  headers.Origin = serverOrigin();
  if (options?.body instanceof FormData) {
    return fetch(`${serverOrigin()}/api${path}`, { ...options, headers });
  }
  const binary = /\/(file|export|pages\/\d+)(\?|$)/.test(path);
  const response = await CapacitorHttp.request({
    url: `${serverOrigin()}/api${path}`,
    method: options?.method || "GET",
    headers,
    ...(options?.body ? { data: JSON.parse(String(options.body)) } : {}),
    responseType: binary
      ? "arraybuffer"
      : path.endsWith("/plan")
        ? "text"
        : "json",
    connectTimeout: 4000,
    readTimeout: 15000,
    disableRedirects: true,
  });
  const body = binary
    ? Uint8Array.from(atob(response.data), (value) => value.charCodeAt(0))
    : typeof response.data === "string"
      ? response.data
      : JSON.stringify(response.data);
  return new Response(response.status === 204 ? null : body, {
    status: response.status,
    headers: response.headers,
  });
}

function cached(path: string) {
  const snapshot = state.snapshot;
  if (!snapshot || state.locked)
    throw new Error(
      "Connect to your computer and sign in to download your plans first.",
    );
  if (path === "/auth/session") return snapshot.account;
  if (path === "/care/personal" || path === "/care") return snapshot.workspace;
  if (path === "/reports") return snapshot.reports;
  const url = new URL(path, "https://aftercare.invalid");
  if (url.pathname === "/care/today")
    return phoneToday(
      snapshot,
      url.searchParams.get("patient_id") || "",
      state.queue,
    );
  const match = url.pathname.match(
    /^\/reports\/([^/]+)(?:\/(schedules|activity|overview))?$/,
  );
  if (match && snapshot.reports.some((report) => report.id === match[1])) {
    if (match[2] === "schedules")
      return phoneSchedules(
        snapshot,
        match[1],
        state.queue,
        url.searchParams.get("day") || undefined,
      );
    if (match[2] === "activity") return snapshot.activities[match[1]];
    if (!match[2])
      return snapshot.reports.find((report) => report.id === match[1]);
  }
  throw new Error(
    "This action needs a connection. Your downloaded plans and dose recording remain available.",
  );
}

async function cancelNotifications() {
  const pending = await LocalNotifications.getPending();
  if (pending.notifications.length)
    await LocalNotifications.cancel({
      notifications: pending.notifications.map(({ id }) => ({ id })),
    });
}
let scheduling = Promise.resolve();
export function refreshPhoneNotifications() {
  const operation = scheduling.then(async () => {
    if (!state.enabled || state.locked || state.needsRefresh || !state.snapshot)
      return cancelNotifications();
    if ((await LocalNotifications.checkPermissions()).display !== "granted") {
      state.enabled = false;
      await save();
      return cancelNotifications();
    }
    const now = Date.now();
    const expires = Date.parse(state.snapshot.valid_until);
    const notifications = Object.keys(state.snapshot.schedules)
      .flatMap((id) =>
        phoneSchedules(state.snapshot!, id, state.queue)
          .filter((schedule) =>
            ["active", "approved"].includes(schedule.status),
          )
          .flatMap((schedule) =>
            schedule.offline_doses
              .filter((dose) => dose.status === "pending")
              .map((dose) => ({
                at: Date.parse(dose.snoozed_until || dose.due_at),
                due: dose.due_at,
                schedule: schedule.id,
              })),
          ),
      )
      .filter((value) => value.at > now && value.at < expires)
      .sort((a, b) => a.at - b.at)
      .slice(0, 256);
    await cancelNotifications();
    const exact =
      (await LocalNotifications.checkExactNotificationSetting()).exact_alarm ===
      "granted";
    if (notifications.length)
      await LocalNotifications.schedule({
        notifications: notifications.map((value, index) => ({
          id: index + 1,
          title: "AfterCare reminder",
          body: "A medicine reminder is ready. Open AfterCare to check your plan.",
          schedule: { at: new Date(value.at), allowWhileIdle: true },
          isExactNotification: exact,
          channelId: "aftercare-doses-v1",
          extra: { scheduleId: value.schedule, dueAt: value.due },
        })),
      });
  });
  scheduling = operation.catch(() => {});
  return operation;
}

export async function enablePhoneNotifications(enabled: boolean) {
  await initialize();
  if (enabled) {
    if ((await LocalNotifications.requestPermissions()).display !== "granted")
      throw new Error(
        "Allow notifications in Android settings to receive medicine reminders.",
      );
    await LocalNotifications.createChannel({
      id: "aftercare-doses-v1",
      name: "Medicine reminders",
      importance: 4,
      visibility: 0,
    });
  }
  state.enabled = enabled;
  await save();
  await refreshPhoneNotifications();
}

export async function syncPhone() {
  if (!isPhone || signingOut) return;
  await initialize();
  if (syncing) return syncing;
  syncing = (async () => {
    const session = await phoneFetch("/auth/session");
    if (session.status === 401) {
      state.locked = true;
      connected = true;
      await save();
      await cancelNotifications();
      window.dispatchEvent(new Event("aftercare-signed-out"));
      throw new Error("Sign in again to sync your saved recordings.");
    }
    if (!session.ok)
      throw new Error("The server could not check your account.");
    const account = await session.json();
    if (
      state.snapshot &&
      state.snapshot.account.id !== account.id &&
      state.queue.length
    )
      throw new Error(
        `Sign in as ${state.snapshot.account.username} to sync pending recordings before switching accounts.`,
      );
    if (state.snapshot?.account.id !== account.id) {
      state.snapshot = undefined;
      state.queue = [];
      state.enabled = false;
    }
    state.locked = false;
    connected = true;
    for (const entry of state.queue.filter((value) => !value.conflict)) {
      if (
        state.queue.some(
          (value) =>
            value.conflict &&
            value.scheduleId === entry.scheduleId &&
            value.body.due_at === entry.body.due_at,
        )
      ) {
        entry.conflict = "An earlier recording for this dose needs review.";
        continue;
      }
      const result = await phoneFetch(
        `/reports/${entry.reportId}/schedules/${entry.scheduleId}/dose`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(entry.body),
        },
      );
      if (result.ok) {
        if (state.snapshot)
          mergeServerSchedules(
            state.snapshot,
            entry.reportId,
            await result.json(),
          );
        state.queue = state.queue.filter((value) => value !== entry);
      } else if ([403, 404, 409, 422].includes(result.status)) {
        const detail = await result.json().catch(() => ({}));
        entry.conflict =
          typeof detail.detail === "string"
            ? detail.detail
            : "This recording needs review against the current plan.";
      } else
        throw new Error(
          "Some recordings could not sync. They remain saved on your phone.",
        );
      await save();
    }
    const response = await phoneFetch("/mobile/snapshot");
    if (!response.ok)
      throw new Error("Your phone could not refresh its downloaded plans.");
    state.snapshot = await response.json();
    state.needsRefresh = false;
    await save();
    lastError = "";
    await refreshPhoneNotifications().catch(() => {
      lastError =
        "Your records synced, but phone reminders could not be refreshed. Check notification settings.";
    });
    window.dispatchEvent(new Event("aftercare-dose-updated"));
  })()
    .catch((error) => {
      connected = false;
      if (!(error instanceof Error))
        error = new Error("The connection could not be completed.");
      lastError = error.message;
      throw error;
    })
    .finally(() => {
      syncing = undefined;
      emit();
    });
  emit();
  return syncing;
}

export async function phoneRequest(
  path: string,
  options?: RequestInit,
): Promise<Response> {
  await initialize();
  const method = options?.method || "GET";
  if (path === "/auth/logout") {
    if (state.queue.length)
      throw new Error(
        "Sync or review your saved dose recordings before signing out.",
      );
    signingOut = true;
    try {
      await syncing?.catch(() => {});
      try {
        await phoneFetch(path, options);
      } catch {
        /* Local sign-out still clears the phone. */
      }
      await CapacitorCookies.clearAllCookies();
      await scheduling;
      await cancelNotifications();
      await writing;
      await vault.clear();
      state = {
        version: 1,
        origin: serverOrigin(),
        queue: [],
        enabled: false,
        locked: false,
      };
      connected = false;
      lastError = "";
      emit();
      return json({});
    } finally {
      signingOut = false;
    }
  }
  const dose = path.match(/^\/reports\/([^/]+)\/schedules\/([^/]+)\/dose$/);
  if (
    dose &&
    method === "POST" &&
    state.snapshot?.schedules[dose[1]]?.some((value) => value.id === dose[2])
  ) {
    if (state.locked) throw new Error("Sign in again before recording a dose.");
    if (state.needsRefresh)
      throw new Error(
        "Reconnect to verify your plan change before recording another dose.",
      );
    const entry = queueDose(
      state.snapshot,
      state.queue,
      dose[1],
      dose[2],
      JSON.parse(String(options?.body)),
      crypto.randomUUID(),
    );
    state.queue.push(entry);
    try {
      await save();
    } catch (error) {
      state.queue = state.queue.filter((value) => value !== entry);
      throw error;
    }
    await refreshPhoneNotifications().catch(() => {
      lastError =
        "Your dose was saved on this phone, but reminders could not be refreshed.";
    });
    try {
      await syncPhone();
    } catch {
      connected = false;
      emit();
    }
    if (entry.conflict) return json({ detail: entry.conflict }, 409);
    return json(phoneSchedules(state.snapshot, dose[1], state.queue));
  }
  if (
    method !== "GET" &&
    path !== "/care/personal" &&
    !path.startsWith("/auth/") &&
    state.queue.length
  ) {
    await syncPhone();
    if (state.queue.length)
      throw new Error(
        "Review the saved dose conflicts before changing your plans.",
      );
  }
  const affectsPlan =
    method !== "GET" &&
    (/\/(fields|review|reread|archive|restore|delete|reminders|stop)(\/|$)/.test(
      path,
    ) ||
      method === "DELETE");
  if (affectsPlan) {
    state.needsRefresh = true;
    await save();
    await cancelNotifications();
  }
  try {
    const response = await phoneFetch(path, options);
    connected = true;
    if (response.status === 401) {
      state.locked = true;
      await save();
      await cancelNotifications();
    }
    if (
      response.ok &&
      ["/auth/session", "/auth/login", "/auth/register"].includes(path)
    ) {
      const account = await response.clone().json();
      if (state.snapshot?.account.id !== account.id && state.queue.length) {
        state.locked = true;
        await save();
        await phoneFetch("/auth/logout", { method: "POST" });
        throw new Error(
          `Sign in as ${state.snapshot!.account.username} to sync saved recordings first.`,
        );
      }
      void syncPhone().catch(() => {});
    } else if (response.ok && method !== "GET" && !path.startsWith("/push/")) {
      void syncPhone().catch(() => {});
    }
    if (affectsPlan && !response.ok) void syncPhone().catch(() => {});
    emit();
    return response;
  } catch (error) {
    connected = false;
    emit();
    if (method === "GET" || path === "/care/personal")
      return json(cached(path));
    throw error instanceof Error
      ? error
      : new Error("Connect to your computer to complete this action.");
  }
}

export async function keepServerRecording(requestId: string) {
  await initialize();
  const conflict = state.queue.find(
    (entry) => entry.conflict && entry.body.offline.request_id === requestId,
  );
  if (!conflict) return;
  state.reviewedConflicts = [...(state.reviewedConflicts || []), conflict];
  state.queue = state.queue.filter((entry) => entry !== conflict);
  await save();
}

export async function openPhoneDocument(path: string, name: string) {
  const response = await CapacitorHttp.request({
    url: `${serverOrigin()}/api${path}`,
    method: "GET",
    headers: { Origin: serverOrigin() },
    responseType: "arraybuffer",
    connectTimeout: 4000,
    readTimeout: 30000,
  });
  if (response.status !== 200)
    throw new Error("Connect and sign in to open the original document.");
  const mime =
    response.headers["Content-Type"] ||
    response.headers["content-type"] ||
    "application/octet-stream";
  await vault.openFile({ data: response.data, name, mime });
}
