const initial = {
  version: 1,
  account: { id: "fictional-owner", username: "fictional-owner" },
  workspace: {
    patients: [
      { id: "patient", access_role: "owner", episodes: [{ id: "episode" }] },
    ],
    invitations: [],
    legacy_count: 0,
  },
  reports: [{ id: "report", episode_id: "episode" }],
  activities: { report: { medications: [], visits: [] } },
  schedules: {
    report: [
      {
        id: "schedule",
        report_id: "report",
        fingerprint: "a".repeat(64),
        status: "active",
        history: [],
        payload: {
          name: "Fictional medicine",
          dose: "1 tablet",
          timezone: "UTC",
        },
        doses: [],
        offline_doses: [-3600000, 7200000].map((offset) => ({
          due_at: new Date(Date.now() + offset).toISOString(),
          status: "pending",
          recorded_at: null,
          actor_id: null,
          note: "",
          snoozed_until: null,
        })),
      },
    ],
  },
  synced_at: new Date().toISOString(),
  valid_until: new Date(Date.now() + 7 * 86400000).toISOString(),
};
const server = JSON.parse(localStorage.getItem("fixture-server") || "null") || {
  snapshot: initial,
  receipts: [],
  writes: 0,
};
localStorage.setItem("fixture-server", JSON.stringify(server));
let mode = localStorage.getItem("fixture-mode") || "online";
let pending = [];
const response = (data, status = 200) => ({
  data,
  status,
  headers: { "Content-Type": "application/json" },
});
window.CapacitorCustomPlatform = { name: "android" };
window.Capacitor = {
  PluginHeaders: [
    {
      name: "PhoneVault",
      methods: ["load", "save", "clear"].map((name) => ({
        name,
        rtype: "promise",
      })),
    },
    { name: "CapacitorHttp", methods: [{ name: "request", rtype: "promise" }] },
    {
      name: "CapacitorCookies",
      methods: [{ name: "clearAllCookies", rtype: "promise" }],
    },
    {
      name: "LocalNotifications",
      methods: [
        "getPending",
        "cancel",
        "checkPermissions",
        "requestPermissions",
        "createChannel",
        "checkExactNotificationSetting",
        "schedule",
      ].map((name) => ({ name, rtype: "promise" })),
    },
  ],
  nativePromise: async (plugin, method, options) => {
    if (plugin === "PhoneVault") {
      if (method === "load")
        return { value: localStorage.getItem("fixture-vault") };
      if (method === "save")
        localStorage.setItem("fixture-vault", options.value);
      if (method === "clear") localStorage.removeItem("fixture-vault");
      return {};
    }
    if (plugin === "LocalNotifications") {
      if (method === "getPending") return { notifications: pending };
      if (method === "cancel") pending = [];
      if (method === "schedule") pending = options.notifications;
      return {
        display: "granted",
        exact_alarm: "granted",
        notifications: pending,
      };
    }
    if (plugin === "CapacitorCookies") return {};
    if (mode === "offline") throw new Error("Fictional network disconnected");
    const path = new URL(options.url).pathname;
    if (path === "/api/auth/session") return response(server.snapshot.account);
    if (path === "/api/mobile/snapshot") return response(server.snapshot);
    if (path === "/api/reports/report/schedules/schedule/dose") {
      const body = options.data;
      if (!server.receipts.includes(body.offline.request_id)) {
        server.receipts.push(body.offline.request_id);
        server.writes++;
        const dose = server.snapshot.schedules.report[0].offline_doses.find(
          (value) => value.due_at === body.due_at,
        );
        Object.assign(dose, {
          status: body.action,
          recorded_at: new Date().toISOString(),
        });
        server.snapshot.schedules.report[0].doses = [dose];
        localStorage.setItem("fixture-server", JSON.stringify(server));
      }
      if (mode === "lose-reply") {
        mode = "offline";
        localStorage.setItem("fixture-mode", mode);
        throw new Error("Reply lost after server saved the record");
      }
      return response(server.snapshot.schedules.report);
    }
    if (path.endsWith("/fields/source")) {
      mode = "offline";
      localStorage.setItem("fixture-mode", mode);
      throw new Error("Reply lost during plan edit");
    }
    return response({ detail: "Not available in this fixture" }, 404);
  },
};

const phone = await import("../src/phone.ts");
let result;
let error = "";
function render() {
  document.getElementById("result").textContent = JSON.stringify({
    ...phone.phoneStatus(),
    result,
    error,
    writes: server.writes,
    alerts: pending.length,
  });
}
function button(label, action) {
  const element = document.createElement("button");
  element.textContent = label;
  element.onclick = async () => {
    error = "";
    try {
      result = await action();
    } catch (value) {
      error = value.message;
    }
    render();
  };
  document.getElementById("controls").append(element);
}
button("Connect", async () => {
  mode = "online";
  localStorage.setItem("fixture-mode", mode);
  await phone.syncPhone();
});
button("Disconnect", () => {
  mode = "offline";
  localStorage.setItem("fixture-mode", mode);
});
button("Lose next reply", () => {
  mode = "lose-reply";
});
button("Record taken", async () => {
  result = await (
    await phone.phoneRequest("/reports/report/schedules/schedule/dose", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        due_at: server.snapshot.schedules.report[0].offline_doses[0].due_at,
        action: "taken",
      }),
    })
  ).json();
  return result;
});
button("Load offline plans", async () => {
  await phone.phoneRequest("/auth/session");
  await phone.phoneRequest("/care/personal", { method: "POST" });
  return (await phone.phoneRequest("/care/today?patient_id=patient")).json();
});
button("Enable reminders", () => phone.enablePhoneNotifications(true));
button("Change plan", () =>
  phone.phoneRequest("/reports/report/fields/source", {
    method: "PATCH",
    body: JSON.stringify({ value: "Changed fictional detail" }),
  }),
);
window.addEventListener("aftercare-phone-status", render);
render();
