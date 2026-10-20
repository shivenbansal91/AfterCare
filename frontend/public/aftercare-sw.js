self.addEventListener("push", (event) => {
  let tag = "aftercare-reminder";
  try {
    tag = event.data.json().tag || tag;
  } catch {}
  event.waitUntil(
    self.registration.showNotification("AfterCare reminder", {
      body: "A care reminder is ready. Open AfterCare to check the current instructions.",
      tag,
      data: { url: "/" },
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(
    clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then(async (windows) => {
        const app = windows.find(
          (window) => new URL(window.url).origin === self.location.origin,
        );
        if (app) return app.focus();
        return clients.openWindow("/");
      }),
  );
});
