import { useEffect, useState, type MouseEvent } from "react";
import { App } from "@capacitor/app";
import { LocalNotifications } from "@capacitor/local-notifications";
import { isPhone } from "./phone-platform";
import {
  enablePhoneNotifications,
  keepServerRecording,
  openPhoneDocument,
  phoneStatus,
  refreshPhoneNotifications,
  syncPhone,
} from "./phone";
import { sourceImage } from "./api";

export function PhoneStatus({ shared = false }: { shared?: boolean }) {
  const [status, setStatus] = useState(phoneStatus);
  useEffect(() => {
    if (!isPhone) return;
    const update = () => setStatus(phoneStatus());
    const sync = () => {
      void syncPhone()
        .catch(() => refreshPhoneNotifications())
        .catch(() => {});
    };
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") sync();
    }, 30000);
    window.addEventListener("aftercare-phone-status", update);
    window.addEventListener("online", sync);
    const listener = App.addListener("appStateChange", ({ isActive }) => {
      if (isActive) sync();
    });
    sync();
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("aftercare-phone-status", update);
      window.removeEventListener("online", sync);
      void listener.then((handle) => handle.remove());
    };
  }, []);
  if (!isPhone) return null;
  const expired = status.expires && Date.parse(status.expires) <= Date.now();
  return (
    <section
      className="phone-sync"
      aria-label="Phone storage and synchronization"
    >
      <div className="phone-sync-heading">
        <div>
          <strong>
            {shared
              ? "Shared care needs a connection"
              : expired
                ? "Refresh your downloaded plans"
                : status.connected
                  ? "Saved on this phone"
                  : "Offline access"}
          </strong>
          <small>
            {shared
              ? "Caretaker views check current access online."
              : status.lastSync
                ? `Last updated ${new Date(status.lastSync).toLocaleString()}`
                : "Connect and sign in to download your plans."}
          </small>
        </div>
        <button
          className="text-button"
          disabled={status.syncing}
          onClick={() => {
            void syncPhone().catch(() => {});
          }}
        >
          {status.syncing ? "Syncing…" : "Sync"}
        </button>
      </div>
      {status.pending > 0 && (
        <p role="status">
          {status.pending} dose{" "}
          {status.pending === 1 ? "recording" : "recordings"} saved on your
          phone, waiting to sync. Caretakers will see them after syncing.
        </p>
      )}
      {status.needsRefresh && (
        <p role="status">
          Reconnect to finish checking your plan change. Downloaded details
          remain readable; phone alerts are paused.
        </p>
      )}
      {status.error && (
        <details>
          <summary>Connection details</summary>
          <p>{status.error}</p>
        </details>
      )}
      {!!status.conflicts.length && (
        <details open>
          <summary>{status.conflicts.length} recordings need review</summary>
          {status.conflicts.map((entry) => (
            <div key={entry.body.offline.request_id} className="phone-conflict">
              <strong>
                {entry.medicineName} · {entry.dose}
              </strong>
              <p>
                {entry.body.action} ·{" "}
                {new Date(entry.body.due_at).toLocaleString()}
              </p>
              <p>{entry.conflict}</p>
              <button
                className="secondary"
                onClick={() => {
                  void keepServerRecording(entry.body.offline.request_id);
                }}
              >
                Keep server version
              </button>
            </div>
          ))}
        </details>
      )}
      {!!status.reviewedConflicts.length && (
        <details>
          <summary>Reviewed sync conflicts</summary>
          {status.reviewedConflicts.map((entry) => (
            <div className="phone-conflict" key={entry.body.offline.request_id}>
              <strong>
                {entry.medicineName} · {entry.dose}
              </strong>
              <p>
                {entry.body.action} ·{" "}
                {new Date(entry.body.due_at).toLocaleString()} · Server version
                kept
              </p>
              <p>{entry.conflict}</p>
            </div>
          ))}
        </details>
      )}
      {expired && (
        <p>
          Your saved information remains readable. Reconnect to refresh
          reminders and dose recording.
        </p>
      )}
    </section>
  );
}

export function PhoneNotificationControls() {
  const [status, setStatus] = useState(phoneStatus);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const update = () => setStatus(phoneStatus());
    window.addEventListener("aftercare-phone-status", update);
    return () => window.removeEventListener("aftercare-phone-status", update);
  }, []);
  async function change() {
    setBusy(true);
    try {
      await enablePhoneNotifications(!status.enabled);
      const exact = await LocalNotifications.checkExactNotificationSetting();
      setMessage(
        exact.exact_alarm === "granted"
          ? "Your downloaded plans use device-scheduled reminders."
          : "Reminders are enabled. Allow Alarms & reminders in Android settings for precise timing.",
      );
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="notification-settings">
      <h3>Phone reminders</h3>
      <p>
        Confirmed plans are downloaded for up to seven days. Scheduled alerts
        can work without internet or the app staying open.
      </p>
      <button className="primary wide" disabled={busy} onClick={change}>
        {busy
          ? "Please wait…"
          : status.enabled
            ? "Turn off phone reminders"
            : "Enable phone reminders"}
      </button>
      {status.enabled && (
        <button
          className="secondary wide"
          onClick={async () => {
            await LocalNotifications.changeExactNotificationSetting();
            await refreshPhoneNotifications();
          }}
        >
          Android alarm settings
        </button>
      )}
      {message && <p role="status">{message}</p>}
      <p className="fine-print">
        Reconnect regularly to pick up plan changes. Changes made elsewhere
        cannot reach an offline phone. Permission and Android battery settings
        can affect delivery. Caretaker updates refresh while the test app is
        open and connected.
      </p>
    </section>
  );
}

export function PhoneSourceImage({
  path,
  alt,
  className,
}: {
  path: string;
  alt: string;
  className: string;
}) {
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    if (!isPhone) return;
    let active = true;
    let objectUrl = "";
    void sourceImage(path)
      .then((value) => {
        objectUrl = value;
        if (active) setUrl(value);
        else URL.revokeObjectURL(value);
      })
      .catch(() => {
        if (active) setError("Connect to open the original source image.");
      });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [path]);
  if (error) return <p role="status">{error}</p>;
  if (isPhone && !url) return <p>Loading original…</p>;
  return (
    <img
      className={className}
      src={isPhone ? url : `/api${path}`}
      alt={alt}
      draggable={false}
    />
  );
}

export function openDocument(event: MouseEvent<HTMLElement>) {
  if (!isPhone) return;
  const anchor = (event.target as Element).closest<HTMLAnchorElement>(
    "a[href]",
  );
  if (!anchor || !new URL(anchor.href).pathname.startsWith("/api/")) return;
  event.preventDefault();
  const path = new URL(anchor.href).pathname.replace(/^\/api/, "");
  const name = path.endsWith("/plan")
    ? "aftercare-plan.html"
    : "aftercare-document.pdf";
  void openPhoneDocument(path, name).catch((error) =>
    window.alert(error.message),
  );
}
