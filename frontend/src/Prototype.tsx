import { useEffect, useRef, useState, type ChangeEvent } from "react";
import { MotionConfig } from "motion/react";
import * as Select from "@radix-ui/react-select";
import {
  ArrowLeft,
  ArrowRight,
  ArrowsClockwise,
  Archive,
  BellSimple,
  CalendarBlank,
  CaretRight,
  CaretDown,
  CaretUp,
  Check,
  CheckCircle,
  ClipboardText,
  DownloadSimple,
  DotsThree,
  FileText,
  FirstAidKit,
  House,
  Info,
  MagnifyingGlass,
  Pill,
  Phone,
  Plus,
  Printer,
  ShieldCheck,
  SignOut,
  Sparkle,
  Stethoscope,
  UploadSimple,
  Users,
  UserCircle,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import {
  BottomSheet,
  Carousel,
  KeyboardInput,
  MobileScroll,
  useKeyboard,
  useKeyboardInsets,
  useScreenPortal,
} from "./mobile";
import {
  api,
  downloadReport,
  jsonRequest,
  type Account,
  type Routine,
  type Patient,
  type AlertPreferences,
  type Timing,
  type MedicineInfo,
  type TodayDose,
  type CareNotification,
  type Schedule,
  type Reminder,
  type Workspace,
  type CareAudit,
  type Activity,
  type CareField,
  type Report,
  type ArchivedReport,
  type Visit,
  type VisitItem,
} from "./api";
import { careSummary, medicines, savedMedicines } from "./care-summary";
import "@fontsource/manrope/400.css";
import "@fontsource/manrope/500.css";
import "@fontsource/manrope/600.css";
import "@fontsource/manrope/700.css";
type Screen =
  "Home" | "Meds" | "Reports" | "Visits" | "Family" | "Review" | "Plan";
const tabs = [
  { name: "Home", icon: House },
  { name: "Meds", icon: Pill },
  { name: "Reports", icon: FileText },
  { name: "Visits", icon: CalendarBlank },
  { name: "Family", icon: Users },
] as const;
const statusText = {
  pending: "Needs review",
  confirmed: "Reviewed",
  rejected: "Excluded",
  clarify: "Needs clarification",
};
const screenTitles: Record<Screen, string> = {
  Home: "Home",
  Meds: "Your medications",
  Reports: "Health reports",
  Visits: "Upcoming care",
  Family: "Your care circle",
  Review: "Review your report",
  Plan: "Reviewed instructions",
};
function accessEventDetail(event: CareAudit) {
  if (["invited", "accepted", "declined", "revoked"].includes(event.action)) {
    const role = event.detail.split(" / ").at(-1);
    const permission =
      role === "recorder" ? "View and record care" : "View only";
    return [event.recipient_name, permission].filter(Boolean).join(" · ");
  }
  return event.detail;
}
function SectionHeading({
  title,
  action,
  onClick,
}: {
  title: string;
  action?: string;
  onClick?: () => void;
}) {
  return (
    <div className="section-heading">
      <h2>{title}</h2>
      {action && (
        <button className="text-button" onClick={onClick}>
          {action}
          <CaretRight size={13} />
        </button>
      )}
    </div>
  );
}
function CareSelect({
  label,
  value,
  onChange,
  options,
  placeholder = "Choose an option",
  disabled = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string; disabled?: boolean }[];
  placeholder?: string;
  disabled?: boolean;
}) {
  const keyboard = useKeyboard();
  const { screenRef } = useScreenPortal();
  return (
    <Select.Root
      value={value}
      onValueChange={onChange}
      disabled={disabled || !options.length}
      onOpenChange={(open) => {
        if (open) keyboard.hide();
      }}
    >
      <Select.Trigger className="choice-trigger" aria-label={label}>
        <Select.Value placeholder={placeholder}>
          {options.find((option) => option.value === value)?.label}
        </Select.Value>
        <Select.Icon>
          <CaretDown size={15} />
        </Select.Icon>
      </Select.Trigger>
      <Select.Portal container={screenRef.current ?? undefined}>
        <Select.Content
          className="choice-menu"
          position="popper"
          sideOffset={6}
          align="start"
          collisionBoundary={screenRef.current}
          collisionPadding={12}
        >
          <Select.ScrollUpButton className="choice-scroll">
            <CaretUp size={14} />
          </Select.ScrollUpButton>
          <Select.Viewport className="choice-options">
            {options.map((option) => (
              <Select.Item
                className="choice-item"
                key={option.value}
                value={option.value}
                disabled={option.disabled}
              >
                <Select.ItemText>{option.label}</Select.ItemText>
                <Select.ItemIndicator className="choice-check">
                  <Check size={16} weight="bold" />
                </Select.ItemIndicator>
              </Select.Item>
            ))}
          </Select.Viewport>
          <Select.ScrollDownButton className="choice-scroll">
            <CaretDown size={14} />
          </Select.ScrollDownButton>
        </Select.Content>
      </Select.Portal>
    </Select.Root>
  );
}
export default function Prototype() {
  const { screenRef } = useScreenPortal();
  useEffect(() => {
    const screen = screenRef.current;
    if (!screen) return;
    // Focus must scroll MobileScroll content, not the fixed phone viewport.
    const keepViewportFixed = () => {
      if (screen.scrollTop || screen.scrollLeft) screen.scrollTo(0, 0);
    };
    screen.addEventListener("scroll", keepViewportFixed);
    keepViewportFixed();
    return () => screen.removeEventListener("scroll", keepViewportFixed);
  }, [screenRef]);
  const [account, setAccount] = useState<Account | null>(null);
  const [loading, setLoading] = useState(true);
  const [register, setRegister] = useState(false);
  const [recovering, setRecovering] = useState(false);
  const [recoveryInput, setRecoveryInput] = useState("");
  const [recoveryConfirm, setRecoveryConfirm] = useState("");
  const [authNotice, setAuthNotice] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const keyboard = useKeyboard();
  useEffect(() => {
    api<Account>("/auth/session")
      .then(setAccount)
      .catch(() => {})
      .finally(() => setLoading(false));
    const expired = () => {
      setAccount(null);
      setPassword("");
      setRegister(false);
      setRecovering(false);
      setRecoveryInput("");
      setRecoveryConfirm("");
      setAuthNotice("");
      setError("Your session ended. Sign in to continue.");
    };
    window.addEventListener("aftercare-signed-out", expired);
    return () => window.removeEventListener("aftercare-signed-out", expired);
  }, []);
  async function authenticate(event: React.FormEvent) {
    event.preventDefault();
    keyboard.hide();
    setBusy(true);
    setError("");
    try {
      if (recovering) {
        if (password !== recoveryConfirm) {
          setError("The new passwords do not match.");
          return;
        }
        await api(
          "/auth/recover",
          jsonRequest("POST", {
            username,
            recovery_code: recoveryInput,
            new_password: password,
          }),
        );
        setRecovering(false);
        setRecoveryInput("");
        setRecoveryConfirm("");
        setPassword("");
        setAuthNotice(
          "Password reset. Sign in with your new password, then create a new recovery code.",
        );
        return;
      }
      setAccount(
        await api<Account>(
          register ? "/auth/register" : "/auth/login",
          jsonRequest("POST", { username, password }),
        ),
      );
      setPassword("");
      setRegister(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Sign-in failed.");
    } finally {
      setBusy(false);
    }
  }
  async function signOut() {
    if (account) {
      const id = localStorage.getItem(`aftercare-push-${account.id}`);
      if (id) await api(`/push/devices/${id}`, { method: "DELETE" });
      localStorage.removeItem(`aftercare-push-${account.id}`);
      localStorage.removeItem(`aftercare-alerts-${account.id}`);
    }
    await api("/auth/logout", { method: "POST" });
    keyboard.hide();
    setAccount(null);
    setRegister(false);
    setRecovering(false);
    setRecoveryInput("");
    setRecoveryConfirm("");
    setAuthNotice("");
    setPassword("");
    setError("");
  }
  if (account)
    return <RecoveryApp key={account.id} account={account} signOut={signOut} />;
  return (
    <MotionConfig reducedMotion="user">
      <div className="aftercare-app">
        <MobileScroll className="aftercare-scroll">
          <main className="care-content account-screen">
            <FirstAidKit size={44} weight="duotone" />
            <h1>
              Your medicines.
              <br />
              Your routine.
            </h1>
            <p className="intro">
              Keep your care plans and your people together in one private
              installation.
            </p>
            {loading ? (
              <p role="status">Opening AfterCare…</p>
            ) : (
              <form className="plain-card account-form" onSubmit={authenticate}>
                <h2>
                  {recovering
                    ? "Recover your account"
                    : register
                      ? "Create a local account"
                      : "Welcome back"}
                </h2>
                {authNotice && (
                  <p role="status" className="success-banner">
                    {authNotice}
                  </p>
                )}
                <label className="activity-label">
                  Username
                  <KeyboardInput
                    aria-label="Username"
                    autoComplete="username"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    onBlur={() => keyboard.hide()}
                    minLength={3}
                    maxLength={40}
                    pattern="[a-zA-Z0-9_-]+"
                    required
                  />
                </label>
                {recovering && (
                  <label className="activity-label">
                    Recovery code
                    <KeyboardInput
                      aria-label="Recovery code"
                      type="password"
                      value={recoveryInput}
                      onChange={(e) => setRecoveryInput(e.target.value)}
                      onBlur={() => keyboard.hide()}
                      autoComplete="off"
                      maxLength={128}
                      required
                    />
                  </label>
                )}
                <label className="activity-label">
                  {recovering ? "New password" : "Password"}
                  <KeyboardInput
                    aria-label={recovering ? "New password" : "Password"}
                    type="password"
                    autoComplete={
                      register || recovering
                        ? "new-password"
                        : "current-password"
                    }
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    onBlur={() => keyboard.hide()}
                    minLength={12}
                    maxLength={128}
                    required
                  />
                </label>
                <p className="fine-print">
                  {recovering
                    ? "Use the single-use recovery code saved from Account security. This signs out all sessions. Without a saved code, the app cannot reset your password."
                    : "At least 12 characters. Set up a recovery code in Account security after signing in."}
                </p>
                {recovering && (
                  <label className="activity-label">
                    Confirm new password
                    <KeyboardInput
                      aria-label="Confirm new password"
                      type="password"
                      autoComplete="new-password"
                      value={recoveryConfirm}
                      onChange={(e) => setRecoveryConfirm(e.target.value)}
                      onBlur={() => keyboard.hide()}
                      minLength={12}
                      maxLength={128}
                      required
                    />
                  </label>
                )}
                {error && (
                  <p className="error-banner" role="alert">
                    {error}
                  </p>
                )}
                <button
                  className="primary wide"
                  type="submit"
                  disabled={busy}
                  onPointerDown={(e) => e.preventDefault()}
                >
                  {busy
                    ? "Please wait…"
                    : recovering
                      ? "Reset password"
                      : register
                        ? "Create account"
                        : "Sign in"}
                  <ArrowRight size={18} />
                </button>
                <button
                  className="text-button"
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    keyboard.hide();
                    setRecovering(false);
                    setRecoveryInput("");
                    setRecoveryConfirm("");
                    setPassword("");
                    setAuthNotice("");
                    setRegister(recovering ? false : !register);
                    setError("");
                  }}
                >
                  {recovering
                    ? "Back to sign in"
                    : register
                      ? "Already have an account? Sign in"
                      : "New here? Create an account"}
                </button>
                {!register && !recovering && (
                  <button
                    className="text-button"
                    type="button"
                    disabled={busy}
                    onClick={() => {
                      keyboard.hide();
                      setRecovering(true);
                      setPassword("");
                      setError("");
                      setAuthNotice("");
                    }}
                  >
                    Forgot password? Use recovery code
                  </button>
                )}
              </form>
            )}
            <p className="fine-print">
              AfterCare · Local document processing. Confirm prescription
              details and reminder times before starting.
            </p>
          </main>
        </MobileScroll>
      </div>
    </MotionConfig>
  );
}
function SchedulePanel({
  report,
  isOwner,
  canRecord,
  compact = false,
  onOpen,
  onPending,
  initialSetup = false,
  onSetupHandled,
}: {
  report: Report;
  isOwner: boolean;
  canRecord: boolean;
  compact?: boolean;
  onOpen?: () => void;
  onPending?: (value: boolean) => void;
  initialSetup?: boolean;
  onSetupHandled?: () => void;
}) {
  const keyboard = useKeyboard();
  const [items, setItems] = useState<Schedule[]>([]);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const [group, setGroup] = useState("");
  const [timing, setTiming] = useState<Timing | null>(null);
  const [times, setTimes] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [zone, setZone] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [stopping, setStopping] = useState("");
  const [day, setDay] = useState("");
  const [dayInput, setDayInput] = useState("");
  const meds = medicines(report);
  const base = `/reports/${report.id}/schedules`;
  const list = base + (day ? `?day=${encodeURIComponent(day)}` : "");
  const refresh = async () => {
    try {
      setItems(await api<Schedule[]>(list));
      setLoaded(true);
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  };
  useEffect(() => {
    let active = true;
    const load = () =>
      api<Schedule[]>(list)
        .then((value) => {
          if (active) {
            setItems(value);
            setLoaded(true);
          }
        })
        .catch((e) => {
          if (active) setError(e.message);
        });
    void load();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, 15000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [list, report.plan_saved]);
  const active = items.filter(
    (item) => item.status === "active" || item.status === "approved",
  );
  const next = active
    .flatMap((schedule) =>
      schedule.doses
        .filter((dose) => dose.status === "pending")
        .map((dose) => ({ schedule, dose })),
    )
    .sort((a, b) => a.dose.due_at.localeCompare(b.dose.due_at))[0];
  useEffect(() => {
    onPending?.(!!next);
  }, [!!next, onPending]);
  async function choose(group: string) {
    setGroup(group);
    setTiming(null);
    setError("");
    setConfirmed(false);
    try {
      const value = await api<Timing>(
        `/reports/${report.id}/timing?group=${encodeURIComponent(group)}`,
      );
      setTiming(value);
      setTimes(value.times.join(", "));
      setStart(value.start);
      setEnd(value.end);
      setZone(value.timezone);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  useEffect(() => {
    if (initialSetup && isOwner && report.plan_saved) {
      keyboard.hide();
      setOpen(true);
      void choose(meds[0]?.group || "");
      onSetupHandled?.();
    }
  }, [initialSetup, report.id]);
  async function action(
    schedule: Schedule,
    dose: Schedule["doses"][number],
    action: string,
  ) {
    keyboard.hide();
    setBusy(true);
    setError("");
    try {
      await api(
        `${base}/${schedule.id}/dose`,
        jsonRequest("POST", { due_at: dose.due_at, action }),
      );
      await refresh();
      window.dispatchEvent(new Event("aftercare-dose-updated"));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  if (compact)
    return (
      <div className="plain-card schedule-preview">
        <SectionHeading title="Your reminders" action="View" onClick={onOpen} />
        {!loaded ? (
          <p>Loading reminders…</p>
        ) : next ? (
          <>
            <strong>{next.schedule.payload.name}</strong>
            <p>
              {next.schedule.payload.dose} ·{" "}
              {new Date(next.dose.due_at).toLocaleTimeString([], {
                hour: "2-digit",
                minute: "2-digit",
                timeZone: next.schedule.payload.timezone,
              })}
            </p>
          </>
        ) : (
          <p>No pending reminders today.</p>
        )}
      </div>
    );
  return (
    <section className="schedule-panel">
      <SectionHeading title="Medicine reminders" />
      <div className="reminder-setup-card">
        <p className="panel-help">
          {report.kind === "manual"
            ? "Set reminder times for the medicine details you entered."
            : "Confirm the prescription overview, then choose reminder times."}
        </p>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {!loaded && <p>Loading reminders…</p>}
        {isOwner && (
          <button
            className="primary wide"
            disabled={busy || !report.plan_saved || !meds.length}
            onClick={() => {
              keyboard.hide();
              setOpen(true);
              void choose(meds[0]?.group || "");
            }}
          >
            <BellSimple size={18} />
            Set up reminders
          </button>
        )}
        {!report.plan_saved && (
          <p className="fine-print">
            Confirm the prescription overview first. Missing details can be
            added there.
          </p>
        )}
      </div>
      {!!items.length && (
        <form
          className="schedule-day-filter panel-group"
          onSubmit={(e) => {
            e.preventDefault();
            keyboard.hide();
            setDay(dayInput);
          }}
        >
          <label className="activity-label">
            History date (YYYY-MM-DD)
            <KeyboardInput
              aria-label="Schedule history date"
              placeholder="Leave blank for today"
              value={dayInput}
              onChange={(e) => setDayInput(e.target.value)}
              onBlur={() => keyboard.hide()}
            />
          </label>
          <button
            type="submit"
            className="secondary"
            disabled={!!dayInput && !/^\d{4}-\d{2}-\d{2}$/.test(dayInput)}
          >
            View
          </button>
        </form>
      )}
      {items.map((item) => (
        <article className="schedule-card" key={item.id}>
          <div className="schedule-heading">
            <strong>
              {item.payload.name} {item.payload.strength}
            </strong>
            <span
              className={`small-badge ${["active", "approved"].includes(item.status) ? "green" : "amber"}`}
            >
              {item.status === "approved" ? "Previous schedule" : item.status}
            </span>
          </div>
          <p>
            {item.payload.dose} · {item.payload.times.join(" / ")}
          </p>
          <small>
            {item.payload.start} – {item.payload.end}
            <br />
            {item.payload.timezone}
          </small>
          {item.reason && <p className="fine-print">{item.reason}</p>}
          {item.doses.map((dose) => (
            <div className="scheduled-dose" key={dose.due_at}>
              <div>
                <strong>
                  {new Date(dose.due_at).toLocaleTimeString([], {
                    hour: "2-digit",
                    minute: "2-digit",
                    timeZone: item.payload.timezone,
                  })}
                </strong>
                <span>
                  {dose.status === "pending"
                    ? new Date(dose.due_at).getTime() <= Date.now()
                      ? "Due · not confirmed"
                      : "Upcoming"
                    : dose.status}
                </span>
              </div>
              {dose.snoozed_until && dose.status === "pending" && (
                <small>
                  Alert snoozed until{" "}
                  {new Date(dose.snoozed_until).toLocaleTimeString([], {
                    hour: "2-digit",
                    minute: "2-digit",
                    timeZone: item.payload.timezone,
                  })}
                </small>
              )}
              {canRecord && new Date(dose.due_at).getTime() <= Date.now() && (
                <div className="dose-actions">
                  {dose.status === "pending" ? (
                    <>
                      <button
                        className="primary"
                        disabled={busy}
                        onClick={() => action(item, dose, "taken")}
                      >
                        Taken
                      </button>
                      <button
                        className="secondary"
                        disabled={busy}
                        onClick={() => action(item, dose, "skipped")}
                      >
                        Skipped
                      </button>
                      <button
                        className="text-button"
                        disabled={busy}
                        onClick={() => action(item, dose, "snooze")}
                      >
                        Snooze 10m
                      </button>
                    </>
                  ) : (
                    <button
                      className="text-button"
                      disabled={busy}
                      onClick={() => action(item, dose, "undo")}
                    >
                      Undo record
                    </button>
                  )}
                </div>
              )}
            </div>
          ))}
          {!!item.history?.length && (
            <details className="dose-history">
              <summary>Recent dose history</summary>
              {item.history.map((event) => (
                <div className="clinical-source" key={event.due_at}>
                  <strong>
                    {new Date(event.due_at).toLocaleString()} · {event.status}
                  </strong>
                  <p>{event.note}</p>
                  <small>Recorded by {event.actor_name || "Unknown"}</small>
                </div>
              ))}
            </details>
          )}
          {isOwner &&
            !["stopped", "rejected"].includes(item.status) &&
            (stopping === item.id ? (
              <div className="stop-confirm">
                <p>Stop this reminder? Your past records will remain.</p>
                <button
                  className="secondary wide"
                  disabled={busy}
                  onClick={async () => {
                    setBusy(true);
                    try {
                      await api(`${base}/${item.id}/stop`, { method: "POST" });
                      await refresh();
                      setStopping("");
                      window.dispatchEvent(new Event("aftercare-dose-updated"));
                    } catch (e) {
                      setError((e as Error).message);
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  Stop reminder
                </button>
                <button className="text-button" onClick={() => setStopping("")}>
                  Keep reminder
                </button>
              </div>
            ) : (
              <button
                className="text-button"
                onClick={() => setStopping(item.id)}
              >
                Stop reminder
              </button>
            ))}
        </article>
      ))}
      <BottomSheet
        open={open}
        onOpenChange={setOpen}
        title="Choose reminder times"
      >
        <button
          className="sheet-close"
          aria-label="Close reminder setup"
          onClick={() => {
            keyboard.hide();
            setOpen(false);
          }}
        >
          <X size={20} />
        </button>
        <form
          className="sheet-body account-form reminder-form"
          onSubmit={async (e) => {
            e.preventDefault();
            if (!timing) return;
            keyboard.hide();
            setBusy(true);
            setError("");
            try {
              await api(
                `/reports/${report.id}/reminders`,
                jsonRequest("POST", {
                  group,
                  dose: timing.dose,
                  times: times.split(",").map((value) => value.trim()),
                  start,
                  end,
                  timezone: zone,
                  confirmed,
                  revision: timing.revision,
                }),
              );
              await refresh();
              setOpen(false);
              window.dispatchEvent(new Event("aftercare-dose-updated"));
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <fieldset className="panel-group">
            <legend>Medicine</legend>
            <label className="activity-label">
              Medicine
              <CareSelect
                label="Reminder medicine"
                value={group}
                onChange={(value) => void choose(value)}
                options={meds.map((med) => ({
                  value: med.group,
                  label: med.name,
                }))}
              />
            </label>
          </fieldset>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          {!timing ? (
            <p>Checking prescription timing…</p>
          ) : (
            <>
              <div className="reminder-source panel-notice">
                <strong>
                  Dose: {timing.dose || "Missing—add it in the overview"}
                </strong>
                <p>{timing.explanation}</p>
              </div>
              {!!timing.blocked.length && (
                <p className="error">
                  Confirm or add these details in the overview:{" "}
                  {timing.blocked.join(", ")}.
                </p>
              )}
              <fieldset className="panel-group">
                <legend>Times and dates</legend>
                <label className="activity-label">
                  24-hour times, separated by commas
                  <KeyboardInput
                    aria-label="Reminder times"
                    value={times}
                    onChange={(e) => {
                      setTimes(e.target.value);
                      setConfirmed(false);
                    }}
                    onBlur={() => keyboard.hide()}
                    placeholder="08:00, 20:00"
                    required
                  />
                </label>
                <div className="schedule-dates">
                  <label className="activity-label">
                    {report.kind === "manual"
                      ? "Start reminding on"
                      : "Course start date"}
                    <KeyboardInput
                      aria-label="Reminder start date"
                      value={start}
                      onChange={(e) => {
                        setStart(e.target.value);
                        if (
                          timing?.duration_days &&
                          /^\d{4}-\d{2}-\d{2}$/.test(e.target.value)
                        ) {
                          const date = new Date(e.target.value + "T00:00:00Z");
                          if (!Number.isNaN(date.getTime()))
                            setEnd(
                              new Date(
                                date.getTime() +
                                  (timing.duration_days - 1) * 86400000,
                              )
                                .toISOString()
                                .slice(0, 10),
                            );
                        }
                      }}
                      onBlur={() => keyboard.hide()}
                      placeholder="YYYY-MM-DD"
                      required
                      pattern="[0-9]{4}-[0-9]{2}-[0-9]{2}"
                    />
                  </label>
                  <label className="activity-label">
                    Last reminder date
                    <KeyboardInput
                      aria-label="Reminder end date"
                      value={end}
                      onChange={(e) => setEnd(e.target.value)}
                      onBlur={() => keyboard.hide()}
                      placeholder="YYYY-MM-DD"
                      required
                      pattern="[0-9]{4}-[0-9]{2}-[0-9]{2}"
                    />
                  </label>
                </div>
                <label className="activity-label">
                  Time zone
                  <CareSelect
                    label="Reminder time zone"
                    value={zone}
                    onChange={setZone}
                    options={[
                      ...new Set([
                        zone,
                        "UTC",
                        ...Intl.supportedValuesOf("timeZone"),
                      ]),
                    ]
                      .sort()
                      .map((value) => ({ value, label: value }))}
                  />
                </label>
                <p className="panel-help">
                  Suggested dates use today and any clearly stated number of
                  days. Check the actual course dates. As-needed medicines
                  remain manual records.
                </p>
              </fieldset>
              <label className="consent-check reminder-consent">
                <input
                  type="checkbox"
                  checked={confirmed}
                  onChange={(e) => setConfirmed(e.target.checked)}
                  onPointerDown={(e) => e.preventDefault()}
                  required
                />
                <span>
                  {report.kind === "manual"
                    ? "I checked these times, dates, dose and instructions for the medicine I entered. Start my personal reminders."
                    : "I checked these times, dates, dose and food instructions against my prescription. This sets personal reminders; it does not change my prescription."}
                </span>
              </label>
              <button
                className="primary wide"
                type="submit"
                disabled={busy || !confirmed || !timing.can_schedule}
                onPointerDown={(event) => event.preventDefault()}
              >
                Start reminders <BellSimple size={18} />
              </button>
            </>
          )}
        </form>
      </BottomSheet>
    </section>
  );
}

function RoutineSettings() {
  const keyboard = useKeyboard();
  const [routine, setRoutine] = useState<Routine | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api<Routine>("/care/routine")
      .then(setRoutine)
      .catch((e) => setMessage(e.message));
  }, []);
  return (
    <form
      className="sheet-body account-form routine-settings"
      onSubmit={async (e) => {
        e.preventDefault();
        keyboard.hide();
        setBusy(true);
        try {
          setRoutine(
            await api<Routine>("/care/routine", jsonRequest("PUT", routine)),
          );
          setMessage("Routine saved. Existing reminder times stay unchanged.");
        } catch (e) {
          setMessage((e as Error).message);
        } finally {
          setBusy(false);
        }
      }}
    >
      <div className="panel-notice">
        <CalendarBlank size={23} />
        <div>
          <strong>Make reminders fit your day</strong>
          <p>
            Your routine suggests flexible times. Existing reminders stay
            unchanged.
          </p>
        </div>
      </div>
      {routine && (
        <>
          <fieldset className="panel-group routine-times">
            <legend>Your day</legend>
            {(
              [
                ["wake", "Wake up"],
                ["breakfast", "Breakfast"],
                ["lunch", "Lunch"],
                ["dinner", "Dinner"],
                ["sleep", "Go to sleep"],
              ] as const
            ).map(([key, label]) => (
              <label className="activity-label" key={key}>
                {label}
                <KeyboardInput
                  aria-label={label}
                  value={routine[key]}
                  onChange={(e) =>
                    setRoutine({ ...routine, [key]: e.target.value })
                  }
                  onBlur={() => keyboard.hide()}
                  placeholder="HH:MM"
                  pattern="([01][0-9]|2[0-3]):[0-5][0-9]"
                  required
                />
              </label>
            ))}
          </fieldset>
          <fieldset className="panel-group">
            <legend>Location</legend>
            <label className="activity-label">
              Time zone
              <CareSelect
                label="Routine time zone"
                value={routine.timezone}
                onChange={(timezone) => setRoutine({ ...routine, timezone })}
                options={[
                  ...new Set([
                    routine.timezone,
                    "UTC",
                    ...Intl.supportedValuesOf("timeZone"),
                  ]),
                ]
                  .sort()
                  .map((value) => ({ value, label: value }))}
              />
            </label>
          </fieldset>
          <button className="primary wide" disabled={busy}>
            Save routine
          </button>
        </>
      )}
      {message && <p role="status">{message}</p>}
    </form>
  );
}

function ManualMedicineForm({
  episodeId,
  onSaved,
}: {
  episodeId: string;
  onSaved: (report: Report) => void;
}) {
  const keyboard = useKeyboard();
  const requestId = useRef(crypto.randomUUID());
  const [values, setValues] = useState({
    name: "",
    strength: "",
    dose: "",
    frequency: "Once daily",
    instructions: "",
    duration: "",
    reason: "",
  });
  const [exactTimes, setExactTimes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return (
    <form
      className="sheet-body account-form"
      onSubmit={async (event) => {
        event.preventDefault();
        keyboard.hide();
        setBusy(true);
        setError("");
        try {
          onSaved(
            await api<Report>(
              `/medicines/manual?episode_id=${encodeURIComponent(episodeId)}`,
              jsonRequest("POST", {
                ...values,
                frequency:
                  values.frequency === "Exact times"
                    ? exactTimes
                    : values.frequency,
                request_id: requestId.current,
                confirmed: true,
              }),
            ),
          );
        } catch (e) {
          setError((e as Error).message);
        } finally {
          setBusy(false);
        }
      }}
    >
      <p>
        No prescription needed. Enter the details you already use; they will be
        labelled “Added by you.”
      </p>
      {(
        [
          ["name", "Medicine name", "e.g. Paracetamol"],
          ["strength", "Strength (optional)", "e.g. 500 mg"],
          ["dose", "Dose each time", "e.g. 1 tablet"],
        ] as const
      ).map(([key, label, placeholder]) => (
        <label className="activity-label" key={key}>
          {label}
          <KeyboardInput
            aria-label={label}
            value={values[key]}
            onChange={(e) => setValues({ ...values, [key]: e.target.value })}
            placeholder={placeholder}
            onBlur={() => keyboard.hide()}
            required={key !== "strength"}
            maxLength={200}
          />
        </label>
      ))}
      <label className="activity-label">
        Frequency or exact times
        <CareSelect
          label="Medicine frequency"
          value={values.frequency}
          onChange={(frequency) => setValues({ ...values, frequency })}
          options={[
            "Once daily",
            "Twice daily",
            "Three times daily",
            "Four times daily",
            "Every 6 hours",
            "Every 8 hours",
            "Every 12 hours",
            "As needed",
            "Exact times",
          ].map((value) => ({ value, label: value }))}
        />
      </label>
      {values.frequency === "Exact times" && (
        <label className="activity-label">
          24-hour times, separated by commas
          <KeyboardInput
            aria-label="Exact medicine times"
            pattern="([01][0-9]|2[0-3]):[0-5][0-9](,\s*([01][0-9]|2[0-3]):[0-5][0-9])*"
            value={exactTimes}
            onChange={(e) => setExactTimes(e.target.value)}
            onBlur={() => keyboard.hide()}
            placeholder="08:00, 20:00"
            required
            maxLength={100}
          />
        </label>
      )}
      {(
        [
          [
            "instructions",
            "Meal or sleep instructions (optional)",
            "e.g. After lunch or 30 minutes before breakfast",
          ],
          ["duration", "Duration (optional)", "e.g. 5 days"],
          [
            "reason",
            "What you take it for (optional)",
            "Only a reason you were given or already know",
          ],
        ] as const
      ).map(([key, label, placeholder]) => (
        <label className="activity-label" key={key}>
          {label}
          <KeyboardInput
            aria-label={label}
            value={values[key]}
            onChange={(e) => setValues({ ...values, [key]: e.target.value })}
            placeholder={placeholder}
            onBlur={() => keyboard.hide()}
            maxLength={
              key === "duration" ? 200 : key === "reason" ? 1000 : 2000
            }
          />
        </label>
      ))}
      <p className="fine-print">
        Saving confirms the details you entered. Choose reminder times and dates
        next; as-needed medicines stay manual records.
      </p>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <button
        className="primary wide"
        disabled={busy}
        onPointerDown={(e) => e.preventDefault()}
      >
        {values.frequency === "As needed"
          ? "Save medicine"
          : "Save medicine & choose times"}
      </button>
    </form>
  );
}

function PlanOverview({
  report,
  isOwner,
  onSaved,
}: {
  report: Report;
  isOwner: boolean;
  onSaved: (report: Report) => void;
}) {
  const keyboard = useKeyboard();
  const [current, setCurrent] = useState<Report | null>(null);
  const [fields, setFields] = useState<CareField[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [source, setSource] = useState<CareField | null>(null);
  const [adding, setAdding] = useState(false);
  const [group, setGroup] = useState("Medication 1");
  const [label, setLabel] = useState("Name");
  const [value, setValue] = useState("");
  async function refresh() {
    try {
      const value = await api<Report>(`/reports/${report.id}/overview`);
      setCurrent(value);
      setFields(value.fields.map((field) => ({ ...field })));
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }
  useEffect(() => {
    void refresh();
  }, [report.id]);
  const groups = [...new Set(fields.map((field) => field.group))];
  function change(id: string, patch: Partial<CareField>) {
    setFields(
      fields.map((field) => (field.id === id ? { ...field, ...patch } : field)),
    );
  }
  return (
    <section className="overview">
      <h1>
        Check it all.
        <br />
        Confirm once.
      </h1>
      <p className="intro">
        {report.kind === "manual"
          ? "These details were added by you. Edit them together whenever needed."
          : "Edit anything that needs correcting. Your original document stays intact."}
      </p>
      {error && (
        <p className="error" role="alert">
          {error}
          <button className="text-button" onClick={refresh}>
            Reload current details
          </button>
        </p>
      )}
      {!current && <p>Loading prescription overview…</p>}
      {current && (
        <>
          {report.kind !== "manual" && (
            <a
              className="secondary wide"
              href={`/api/reports/${report.id}/file?inline=true`}
              target="_blank"
              rel="noreferrer"
            >
              <FileText size={18} />
              Open original document
            </a>
          )}
          {report.warnings.map((warning) => (
            <p className="fine-print" key={warning}>
              {warning}
            </p>
          ))}
          {!fields.length && (
            <div className="plain-card">
              <h3>The original is saved</h3>
              <p>
                No details could be identified. Add them from your prescription
                below, or upload a clearer copy.
              </p>
            </div>
          )}
          {groups.map((group) => (
            <section className="overview-group" key={group}>
              <h2>{group}</h2>
              {fields
                .filter((field) => field.group === group)
                .map((field) => (
                  <div
                    className={`overview-field ${field.status === "clarify" ? "needs-attention" : ""}`}
                    key={field.id}
                  >
                    <label className="activity-label">
                      {field.label}
                      <KeyboardInput
                        aria-label={`${group} ${field.label}`}
                        value={field.value}
                        readOnly={!isOwner}
                        onChange={(e) =>
                          change(field.id, { value: e.target.value })
                        }
                        onBlur={() => keyboard.hide()}
                        maxLength={2000}
                      />
                    </label>
                    <div className="overview-meta">
                      <small>
                        {field.origin === "manual" || !field.source
                          ? "Added by you"
                          : `From original · page ${field.source.page + 1}`}
                      </small>
                      {field.source && (
                        <button
                          className="text-button"
                          type="button"
                          onClick={() => {
                            keyboard.hide();
                            setSource(field);
                          }}
                        >
                          View source
                        </button>
                      )}
                    </div>
                    {isOwner && (
                      <div className="field-options">
                        <button
                          type="button"
                          className={
                            field.status === "clarify" ? "selected" : ""
                          }
                          onClick={() =>
                            change(field.id, {
                              status:
                                field.status === "clarify"
                                  ? "pending"
                                  : "clarify",
                            })
                          }
                        >
                          Needs clarification
                        </button>
                        <button
                          type="button"
                          className={
                            field.status === "rejected" ? "selected" : ""
                          }
                          onClick={() =>
                            change(field.id, {
                              status:
                                field.status === "rejected"
                                  ? "pending"
                                  : "rejected",
                            })
                          }
                        >
                          {field.status === "rejected" ? "Excluded" : "Exclude"}
                        </button>
                      </div>
                    )}
                  </div>
                ))}
            </section>
          ))}
          {isOwner && (
            <>
              <button
                className="secondary wide"
                onClick={() => {
                  keyboard.hide();
                  setAdding(true);
                  setValue("");
                }}
              >
                <Plus size={18} />
                Add a missing detail or medicine
              </button>
              <p className="fine-print">
                Blank details stay marked as missing. Medicines with unresolved
                dose or timing details cannot start repeating reminders.
              </p>
              <button
                className="primary wide"
                disabled={busy || !fields.length}
                onClick={async () => {
                  keyboard.hide();
                  setBusy(true);
                  setError("");
                  try {
                    const saved = await api<Report>(
                      `/reports/${report.id}/review`,
                      jsonRequest("PUT", {
                        revision: current.revision,
                        fields: fields.map((field) => ({
                          id: field.id,
                          value: field.value,
                          status:
                            field.status === "rejected"
                              ? "rejected"
                              : field.status === "clarify" ||
                                  !field.value.trim()
                                ? "clarify"
                                : "confirmed",
                        })),
                      }),
                    );
                    onSaved(saved);
                  } catch (e) {
                    setError((e as Error).message);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                Confirm overview & choose reminders <ArrowRight size={18} />
              </button>
            </>
          )}
        </>
      )}
      <BottomSheet
        open={!!source}
        onOpenChange={(open) => !open && setSource(null)}
        title="Original evidence"
      >
        <button
          className="sheet-close"
          aria-label="Close original evidence"
          onClick={() => setSource(null)}
        >
          <X size={20} />
        </button>
        <div className="sheet-body">
          {source?.source && (
            <>
              <p>{source.source.text}</p>
              <div className="overview-source-wrap">
                <img
                  className="overview-source"
                  src={`/api/reports/${report.id}/pages/${source.source.page}`}
                  alt={`Original page ${source.source.page + 1}`}
                  draggable={false}
                />
                {source.source.boxes.map((box, index) => {
                  const page = report.pages[source.source!.page];
                  return (
                    <span
                      className="overview-highlight"
                      key={index}
                      style={{
                        left: `${(box[0] / page.width) * 100}%`,
                        top: `${(box[1] / page.height) * 100}%`,
                        width: `${((box[2] - box[0]) / page.width) * 100}%`,
                        height: `${((box[3] - box[1]) / page.height) * 100}%`,
                      }}
                    />
                  );
                })}
              </div>
              <p className="fine-print">
                {source.group} · {source.label}. Corrections do not rewrite this
                source.
              </p>
            </>
          )}
        </div>
      </BottomSheet>
      <BottomSheet
        open={adding}
        onOpenChange={setAdding}
        title="Add a missing detail"
      >
        <button
          className="sheet-close"
          aria-label="Close add detail"
          onClick={() => {
            keyboard.hide();
            setAdding(false);
          }}
        >
          <X size={20} />
        </button>
        <form
          className="sheet-body account-form"
          onSubmit={async (e) => {
            e.preventDefault();
            keyboard.hide();
            setBusy(true);
            try {
              const next = await api<Report>(
                `/reports/${report.id}/fields`,
                jsonRequest("POST", { group, label, value }),
              );
              const edits = new Map(fields.map((field) => [field.id, field]));
              setCurrent(next);
              setFields(
                next.fields.map((field) => edits.get(field.id) || field),
              );
              setAdding(false);
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <p>
            Copy details from your prescription or instructions you received.
            Add a new medicine's Name, Dose and Frequency before setting
            reminders.
          </p>
          <label className="activity-label">
            Section
            <CareSelect
              label="New detail section"
              value={group}
              onChange={(value) => {
                setGroup(value);
                setLabel(
                  value.startsWith("Medication")
                    ? "Name"
                    : value === "Contacts"
                      ? "Hospital phone"
                      : value === "Patient"
                        ? "Name"
                        : value === "Care team"
                          ? "Hospital"
                          : "Instructions",
                );
              }}
              options={[
                ...new Set([
                  ...groups,
                  ...Array.from(
                    {
                      length: Math.max(
                        3,
                        groups.filter((value) => value.startsWith("Medication"))
                          .length + 1,
                      ),
                    },
                    (_, i) => `Medication ${i + 1}`,
                  ),
                  "Contacts",
                  "Patient",
                  "Care team",
                  "Recovery",
                  "Visits",
                ]),
              ].map((value) => ({ value, label: value }))}
            />
          </label>
          <label className="activity-label">
            Detail
            <CareSelect
              key={group}
              label="New detail label"
              value={label}
              onChange={setLabel}
              options={(group.startsWith("Medication")
                ? [
                    "Name",
                    "Strength",
                    "Dose",
                    "Frequency",
                    "Duration",
                    "Instructions",
                    "Indication",
                  ]
                : group === "Contacts"
                  ? ["Hospital phone", "Doctor phone", "Phone as listed"]
                  : group === "Patient"
                    ? ["Name", "Age", "Date of birth", "Sex"]
                    : group === "Care team"
                      ? ["Hospital", "Doctor", "Clinic/Hospital address"]
                      : ["Instructions", "Diagnosis", "Follow-up"]
              ).map((value) => ({ value, label: value }))}
            />
          </label>
          <label className="activity-label">
            Value
            <KeyboardInput
              aria-label="New detail value"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              onBlur={() => keyboard.hide()}
              required
              maxLength={2000}
            />
          </label>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <button className="primary wide" disabled={busy}>
            Add detail
          </button>
        </form>
      </BottomSheet>
    </section>
  );
}

function MedicineExplanation({
  reportId,
  group,
}: {
  reportId: string;
  group: string;
}) {
  const [info, setInfo] = useState<MedicineInfo | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    const path = `/reports/${reportId}/medicines/`;
    api<MedicineInfo>(`${path}info?group=${encodeURIComponent(group)}`)
      .then((value) => {
        if (active) setInfo(value);
        if (value.matched)
          return api<MedicineInfo>(
            `${path}explain?group=${encodeURIComponent(group)}`,
            { method: "POST" },
          ).then((value) => {
            if (active) setInfo(value);
          });
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [reportId, group]);
  return (
    <div className="medicine-explanation">
      <h3>What is this medicine for?</h3>
      {error && !info ? (
        <p>{error}</p>
      ) : !info ? (
        <p>Checking the reference…</p>
      ) : (
        <>
          {info.facts.map((fact) => (
            <p key={fact}>{fact}</p>
          ))}
          <p className="fine-print">{info.notice}</p>
          {info.reason && (
            <p>
              <strong>
                {info.reason_origin === "document"
                  ? "Reason stated in the document"
                  : "Reason added by you"}
                :
              </strong>{" "}
              {info.reason}
            </p>
          )}
          {info.reason_source && (
            <details className="explanation-evidence">
              <summary>Where this reason is stated</summary>
              <p>{info.reason_source.text}</p>
              <small>Original page {info.reason_source.page + 1}</small>
            </details>
          )}
          {info.context.length > 0 && (
            <div className="report-context">
              <strong>In your report</strong>
              {info.context.map((item) => (
                <div key={item.id}>
                  <p>
                    {item.label}: {item.value}
                  </p>
                  <small>
                    {item.origin === "manual"
                      ? "Added by you"
                      : `From original, page ${(item.source?.page || 0) + 1}`}
                    {item.status !== "confirmed" ? " · Not yet confirmed" : ""}
                  </small>
                  {item.source && (
                    <details className="explanation-evidence">
                      <summary>Source excerpt</summary>
                      <p>{item.source.text}</p>
                    </details>
                  )}
                </div>
              ))}
              {info.context_notice && (
                <p className="fine-print">{info.context_notice}</p>
              )}
            </div>
          )}
          {!info.reason && !info.context.length && (
            <p className="fine-print">
              Your specific reason was not stated. The app does not infer it
              from a diagnosis.
            </p>
          )}
          {info.source_url && (
            <a
              className="text-button"
              href={info.source_url}
              target="_blank"
              rel="noreferrer"
            >
              Read NHS medicine information
            </a>
          )}
        </>
      )}
    </div>
  );
}

function ManualVisitForm({
  episodeId,
  onSaved,
}: {
  episodeId: string;
  onSaved: (report: Report) => void;
}) {
  const keyboard = useKeyboard();
  const requestId = useRef(crypto.randomUUID());
  const [title, setTitle] = useState("");
  const [details, setDetails] = useState("");
  const [date, setDate] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return (
    <form
      className="sheet-body account-form"
      onSubmit={async (event) => {
        event.preventDefault();
        keyboard.hide();
        setBusy(true);
        setError("");
        try {
          onSaved(
            await api<Report>(
              `/visits/manual?episode_id=${encodeURIComponent(episodeId)}`,
              jsonRequest("POST", {
                request_id: requestId.current,
                title,
                details,
                planned_date: date || null,
                note,
                confirmed: true,
              }),
            ),
          );
        } catch (e) {
          setError((e as Error).message);
        } finally {
          setBusy(false);
        }
      }}
    >
      <div className="panel-notice">
        <CalendarBlank size={23} />
        <div>
          <strong>An appointment you add yourself</strong>
          <p>
            Prescription follow-ups stay saved separately. Leave the date blank
            if you haven't booked yet.
          </p>
        </div>
      </div>
      <fieldset className="panel-group">
        <legend>Visit details</legend>
        <label className="activity-label">
          Visit title
          <KeyboardInput
            aria-label="Visit title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onBlur={() => keyboard.hide()}
            placeholder="e.g. Dental check-up"
            maxLength={200}
            required
          />
        </label>
        <label className="activity-label">
          Doctor or location (optional)
          <KeyboardInput
            aria-label="Visit doctor or location"
            value={details}
            onChange={(e) => setDetails(e.target.value)}
            onBlur={() => keyboard.hide()}
            maxLength={1000}
          />
        </label>
      </fieldset>
      <fieldset className="panel-group">
        <legend>Booking</legend>
        <label className="activity-label">
          Appointment date (optional)
          <KeyboardInput
            aria-label="New visit date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            onBlur={() => keyboard.hide()}
            placeholder="YYYY-MM-DD"
            pattern="[0-9]{4}-[0-9]{2}-[0-9]{2}"
            maxLength={10}
          />
        </label>
        <label className="activity-label">
          Note (optional)
          <KeyboardInput
            aria-label="New visit note"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            onBlur={() => keyboard.hide()}
            placeholder="Time, location or a question to ask"
            maxLength={500}
          />
        </label>
      </fieldset>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <button
        className="primary wide"
        type="submit"
        disabled={busy || !title.trim()}
        onPointerDown={(event) => event.preventDefault()}
      >
        Save visit
        <Check size={18} />
      </button>
    </form>
  );
}

function VisitsPanel({
  patientId,
  isOwner,
  canRecord,
  onAdd,
  onOpen,
}: {
  patientId: string;
  isOwner: boolean;
  canRecord: boolean;
  onAdd: () => void;
  onOpen: (item: VisitItem) => void;
}) {
  const [items, setItems] = useState<VisitItem[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    setItems([]);
    setLoaded(false);
    setError("");
    const load = async () => {
      if (!patientId) return;
      try {
        const rows = await api<VisitItem[]>(
          `/care/visits?patient_id=${encodeURIComponent(patientId)}`,
        );
        if (active) {
          setItems(rows);
          setLoaded(true);
          setError("");
        }
      } catch (e) {
        if (active) setError((e as Error).message);
      }
    };
    void load();
    const refresh = () => {
      if (document.visibilityState === "visible") void load();
    };
    const timer = window.setInterval(refresh, 15000);
    window.addEventListener("aftercare-visits-updated", refresh);
    return () => {
      active = false;
      window.clearInterval(timer);
      window.removeEventListener("aftercare-visits-updated", refresh);
    };
  }, [patientId]);
  return (
    <>
      <h1>
        {isOwner ? "Your visits," : "Shared visits,"}
        <br />
        all together.
      </h1>
      <p className="intro">
        {isOwner
          ? "Appointments you add and follow-ups from your prescriptions."
          : "Appointments and prescription follow-ups shared with you."}
      </p>
      {isOwner && (
        <button className="primary wide" onClick={onAdd}>
          <Plus size={18} />
          Add a visit
        </button>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {!loaded && !error && <p role="status">Loading visits…</p>}
      {items.map((item) => {
        const { field, visit } = item;
        const changed =
          visit &&
          (visit.source_value !== field.value || field.status !== "confirmed");
        return (
          <button
            className="visit-card"
            key={`${item.report_id}:${field.id}`}
            onClick={() => onOpen(item)}
          >
            <div className="round-icon">
              {field.label === "Tests" ? (
                <ClipboardText size={25} />
              ) : (
                <CalendarBlank size={25} />
              )}
            </div>
            <span
              className={`small-badge ${field.status === "confirmed" ? "green" : "amber"}`}
            >
              {field.origin === "manual"
                ? isOwner
                  ? "Added by you"
                  : "Manually added"
                : statusText[field.status]}
            </span>
            <h2>{field.label}</h2>
            <p>{field.value}</p>
            <small className="visit-origin">
              {field.origin === "manual"
                ? "User-entered appointment"
                : `From ${item.report_name}`}
            </small>
            {visit && !changed && (
              <div className={`visit-status ${visit.status}`}>
                <CheckCircle size={15} />
                <span>
                  {visit.status === "completed"
                    ? "Completed"
                    : visit.status === "booked" && visit.planned_date
                      ? `Booked for ${new Date(`${visit.planned_date}T12:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}`
                      : "Not booked yet"}
                </span>
              </div>
            )}
            {visit?.actor_name && (
              <span className="record-author">
                Last updated by {visit.actor_name}
              </span>
            )}
            {changed && (
              <p className="changed-source">
                The instruction changed. Check this booking again.
              </p>
            )}
            <span className="text-button">
              {canRecord ? "Manage visit" : "View visit"}
              <CaretRight size={15} />
            </span>
          </button>
        );
      })}
      {loaded && !items.length && (
        <div className="panel-empty visits-empty">
          <span className="settings-row-icon">
            <CalendarBlank size={26} />
          </span>
          <div>
            <strong>No visits yet</strong>
            <p>
              {isOwner
                ? "Add an appointment, or upload a prescription with follow-up instructions."
                : "Appointments and prescription follow-ups shared by the owner appear here."}
            </p>
          </div>
        </div>
      )}
    </>
  );
}

function HomeCare({
  patientId,
  patientName,
  canRecord,
  isOwner,
  onAdd,
  onReview,
  onMeds,
  pendingReport,
  hasPrescription,
}: {
  patientId: string;
  patientName: string;
  canRecord: boolean;
  isOwner: boolean;
  onAdd: () => void;
  onReview: () => void;
  onMeds: (id?: string) => void;
  pendingReport: Report | undefined;
  hasPrescription: boolean;
}) {
  const [doses, setDoses] = useState<TodayDose[]>([]);
  const [reminderPage, setReminderPage] = useState(0);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const currentPatient = useRef(patientId);
  currentPatient.current = patientId;
  const load = async () => {
    if (!patientId) return;
    try {
      const rows = await api<TodayDose[]>(
        `/care/today?patient_id=${patientId}`,
      );
      if (currentPatient.current !== patientId) return;
      setDoses(rows);
      setLoaded(true);
      setError("");
    } catch (e) {
      if (currentPatient.current === patientId) setError((e as Error).message);
    }
  };
  useEffect(() => {
    setLoaded(false);
    setDoses([]);
    setReminderPage(0);
    void load();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, 15000);
    window.addEventListener("aftercare-dose-updated", load);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("aftercare-dose-updated", load);
    };
  }, [patientId]);
  const pendingDoses = doses.filter((dose) => dose.status === "pending");
  const activeReminder = Math.min(
    reminderPage,
    Math.max(0, pendingDoses.length - 1),
  );
  async function record(dose: TodayDose, action: string) {
    setBusy(true);
    try {
      await api(
        `/reports/${dose.report_id}/schedules/${dose.schedule_id}/dose`,
        jsonRequest("POST", { due_at: dose.due_at, action }),
      );
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="home-heading">
        <div>
          <p className="date-label">A little care, every day</p>
          <h1>
            {isOwner
              ? "Your medicines,"
              : `${patientName.split(" ")[0]}'s care,`}
            <br />
            {isOwner ? "within reach." : "at a glance."}
          </h1>
        </div>
        {isOwner && (
          <button
            className="icon-button"
            aria-label="Add medicine"
            onClick={onAdd}
          >
            <Plus size={23} />
          </button>
        )}
      </div>
      {isOwner && pendingReport && (
        <button className="review-strip" onClick={onReview}>
          <FileText size={22} />
          <div>
            <strong>Check your uploaded prescription</strong>
            <span>One editable overview, one confirmation.</span>
          </div>
          <CaretRight size={17} />
        </button>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
          <button className="text-button" onClick={load}>
            Refresh
          </button>
        </p>
      )}
      {!isOwner && loaded && (
        <div className="journey-summary" aria-label="Today's care records">
          <div>
            <strong>
              {doses.filter((dose) => dose.status === "taken").length}
            </strong>
            <span>Taken</span>
          </div>
          <div>
            <strong>
              {doses.filter((dose) => dose.status === "skipped").length}
            </strong>
            <span>Skipped</span>
          </div>
          <div>
            <strong>{pendingDoses.length}</strong>
            <span>Pending</span>
          </div>
        </div>
      )}
      {pendingDoses.length > 1 && (
        <p className="carousel-hint">
          {pendingDoses.length} reminders today{" "}
          <span>
            Swipe to browse <ArrowRight size={13} />
          </span>
        </p>
      )}
      {!loaded && !error ? (
        <div className="plain-card">Loading today's medicines…</div>
      ) : pendingDoses.length ? (
        <div className="reminder-pages">
          <Carousel
            ariaLabel="Today's medicine reminders"
            className="dose-carousel"
            contentClassName="dose-carousel-track"
            paging
            pageIndex={activeReminder}
            onPageChange={setReminderPage}
          >
            {pendingDoses.map((next, index) => (
              <section
                className="hero-card next-dose"
                key={`${next.schedule_id}:${next.due_at}`}
              >
                <span className="pill-label">
                  <Pill size={16} />
                  {index === 0 ? "Next to confirm" : "Medicine reminder"}
                </span>
                <h2>{next.name}</h2>
                {next.strength && <p>{next.strength}</p>}
                <p className="dose-time">
                  {new Date(next.due_at).toLocaleTimeString([], {
                    hour: "2-digit",
                    minute: "2-digit",
                    timeZone: next.timezone,
                  })}
                </p>
                <p>{next.dose}</p>
                <p className="fine-print">
                  {next.timezone} ·{" "}
                  {new Date(next.due_at).getTime() <= Date.now()
                    ? "Due, not confirmed"
                    : "Upcoming"}
                </p>
                {next.snoozed_until &&
                  new Date(next.snoozed_until).getTime() > Date.now() && (
                    <p className="fine-print" role="status">
                      Alert snoozed until{" "}
                      {new Date(next.snoozed_until).toLocaleTimeString([], {
                        hour: "2-digit",
                        minute: "2-digit",
                        timeZone: next.timezone,
                      })}
                    </p>
                  )}
                {canRecord && new Date(next.due_at).getTime() <= Date.now() ? (
                  <div className="dose-actions">
                    <button
                      className="primary"
                      disabled={busy}
                      onClick={() => record(next, "taken")}
                    >
                      <Check size={17} />
                      Taken
                    </button>
                    <button
                      className="secondary"
                      disabled={busy}
                      onClick={() => record(next, "skipped")}
                    >
                      Skipped
                    </button>
                    <button
                      className="text-button"
                      disabled={busy}
                      onClick={() => record(next, "snooze")}
                    >
                      Snooze 10m
                    </button>
                  </div>
                ) : (
                  <button
                    className="primary wide"
                    onClick={() => onMeds(next.report_id)}
                  >
                    View medicine details <ArrowRight size={18} />
                  </button>
                )}
              </section>
            ))}
          </Carousel>
          {pendingDoses.length > 1 && (
            <div
              className="reminder-dots"
              role="group"
              aria-label="Choose a reminder"
            >
              {pendingDoses.map((dose, index) => (
                <button
                  type="button"
                  key={`${dose.schedule_id}:${dose.due_at}`}
                  aria-label={`Show reminder ${index + 1} of ${pendingDoses.length}: ${dose.name}`}
                  aria-current={index === activeReminder ? "true" : undefined}
                  onClick={() => setReminderPage(index)}
                >
                  <span />
                </button>
              ))}
              <span className="pagination-status" role="status">
                Reminder {activeReminder + 1} of {pendingDoses.length}
              </span>
            </div>
          )}
        </div>
      ) : (
        <section className="hero-card next-dose">
          <Pill size={34} weight="duotone" />
          <h2>
            {!isOwner && !doses.length
              ? "No shared reminders today."
              : doses.length
                ? "Today is recorded."
                : hasPrescription
                  ? "Your next step is simple."
                  : "Add your first medicine."}
          </h2>
          <p>
            {!isOwner && !doses.length
              ? "Reminders confirmed by the owner will appear here."
              : doses.length
                ? "No doses are waiting for confirmation today."
                : hasPrescription
                  ? "Set reminder times for the medicines you confirmed."
                  : "Enter a medicine yourself or upload a prescription, then choose your reminder times."}
          </p>
          <button
            className="primary wide"
            onClick={
              !isOwner
                ? () => onMeds()
                : pendingReport
                  ? onReview
                  : hasPrescription
                    ? () => onMeds()
                    : onAdd
            }
          >
            {!isOwner
              ? "View shared medicines"
              : pendingReport
                ? "Review prescription"
                : hasPrescription
                  ? "Set reminder times"
                  : "Add medicine"}
            <Plus size={18} />
          </button>
        </section>
      )}
      <SectionHeading
        title="Today’s medicines"
        action="Manage"
        onClick={() => onMeds()}
      />
      {loaded && !doses.length && (
        <p className="empty-inline">
          Your confirmed reminder plan will appear here.
        </p>
      )}
      {doses.map((dose) => (
        <button
          className="today-dose"
          key={`${dose.schedule_id}:${dose.due_at}`}
          onClick={() => onMeds(dose.report_id)}
        >
          <span className="today-dose-icon">
            <Pill size={22} />
          </span>
          <span>
            <strong>
              {dose.name} {dose.strength}
            </strong>
            <small>
              {dose.dose} ·{" "}
              {new Date(dose.due_at).toLocaleTimeString([], {
                hour: "2-digit",
                minute: "2-digit",
                timeZone: dose.timezone,
              })}
            </small>
          </span>
          <span
            className={`small-badge ${dose.status === "taken" ? "green" : "amber"}`}
          >
            {dose.status === "pending"
              ? new Date(dose.due_at).getTime() > Date.now()
                ? "Upcoming"
                : "Not confirmed"
              : dose.status}
          </span>
        </button>
      ))}
      {isOwner && hasPrescription && (
        <button className="secondary wide" onClick={onAdd}>
          <UploadSimple size={18} />
          Add medicine or prescription
        </button>
      )}
    </>
  );
}

function DeleteReportForm({
  item,
  onDeleted,
}: {
  item: Pick<Report, "id" | "name">;
  onDeleted: () => Promise<void>;
}) {
  const keyboard = useKeyboard();
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return (
    <form
      className="account-form"
      onSubmit={async (e) => {
        e.preventDefault();
        keyboard.hide();
        setBusy(true);
        try {
          await api(
            `/reports/${item.id}`,
            jsonRequest("DELETE", {
              name,
              current_password: password,
              archive_first: true,
            }),
          );
          setPassword("");
          await onDeleted();
        } catch (e) {
          setError((e as Error).message);
        } finally {
          setBusy(false);
        }
      }}
    >
      <h3>{item.name}</h3>
      <p>
        This permanently removes the report, original, reminders and related
        care records. Its reminders will stop. Backups and previously downloaded
        copies remain.
      </p>
      <label className="activity-label">
        Type the exact report name
        <KeyboardInput
          aria-label="Report name for permanent deletion"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onBlur={() => keyboard.hide()}
          required
        />
      </label>
      <label className="activity-label">
        Current password
        <KeyboardInput
          aria-label="Password for permanent deletion"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          onBlur={() => keyboard.hide()}
          required
        />
      </label>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <button
        className="primary wide"
        disabled={busy || name !== item.name || !password}
      >
        Permanently delete report
      </button>
    </form>
  );
}

function AlertChoices({
  value,
  onChange,
}: {
  value: AlertPreferences;
  onChange: (value: AlertPreferences) => void;
}) {
  return (
    <fieldset className="panel-group alert-choices">
      <legend>Dose updates</legend>
      {(
        [
          ["taken", "A dose is marked taken"],
          ["skipped", "A dose is marked skipped"],
          ["unconfirmed", "A dose has not been confirmed"],
        ] as const
      ).map(([key, label]) => (
        <label className="consent-check" key={key}>
          <input
            type="checkbox"
            checked={!!value[key]}
            onPointerDown={(e) => e.preventDefault()}
            onChange={(e) => onChange({ ...value, [key]: e.target.checked })}
          />
          <span>{label}</span>
        </label>
      ))}
      {value.unconfirmed && (
        <label className="activity-label">
          Wait before reporting no confirmation
          <CareSelect
            label="Caretaker alert delay"
            value={String(value.delay_minutes)}
            onChange={(minutes) =>
              onChange({ ...value, delay_minutes: Number(minutes) })
            }
            options={[5, 15, 30, 60, 120, 1440].map((minutes) => ({
              value: String(minutes),
              label: minutes === 1440 ? "24 hours" : `${minutes} minutes`,
            }))}
          />
        </label>
      )}
      <div className="panel-hint">
        <Info size={17} />
        <p>
          No confirmation does not prove a missed dose. Updates appear in the
          caretaker's account; browser notifications require their permission.
        </p>
      </div>
    </fieldset>
  );
}

function CareAlertEditor({
  patientId,
  grant,
  onSaved,
}: {
  patientId: string;
  grant: Patient["sharing"][number];
  onSaved: (workspace: Workspace) => void;
}) {
  const [value, setValue] = useState<AlertPreferences>(grant.alerts);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <details className="care-alert-settings">
      <summary>
        <BellSimple size={17} />
        Notification settings
        <CaretDown size={14} />
      </summary>
      <AlertChoices value={value} onChange={setValue} />
      <button
        className="secondary wide"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          try {
            onSaved(
              await api<Workspace>(
                `/care/patients/${patientId}/invitations/${grant.id}/alerts`,
                jsonRequest("PUT", value),
              ),
            );
            setMessage("Notification preferences saved.");
          } catch (e) {
            setMessage((e as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        Save notification preferences
      </button>
      {message && <p role="status">{message}</p>}
    </details>
  );
}

function CareUpdates({
  onOpen,
  patientId,
}: {
  onOpen: (reportId: string) => void;
  patientId?: string;
}) {
  const [items, setItems] = useState<CareNotification[]>([]);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    let active = true;
    const load = () =>
      api<CareNotification[]>("/care/notifications")
        .then((value) => {
          if (active) {
            setItems(value);
            setLoaded(true);
            setError("");
          }
        })
        .catch((e) => {
          if (active) setError(e.message);
        });
    void load();
    const timer = window.setInterval(load, 15000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);
  const visible = patientId
    ? items.filter((item) => item.patient_id === patientId)
    : items;
  return (
    <section className="care-updates">
      <SectionHeading title="Care circle updates" />
      {error ? (
        <p role="alert">{error}</p>
      ) : !loaded ? (
        <p>Loading updates…</p>
      ) : !visible.length ? (
        <div className="notification-empty">
          <span className="notification-icon">
            <Users size={20} />
          </span>
          <div>
            <strong>No care updates yet</strong>
            <p>Shared care activity will appear here.</p>
          </div>
        </div>
      ) : (
        visible.map((item) => (
          <article
            className={`care-update ${item.read_at ? "" : "unread"}`}
            key={item.id}
          >
            <div className="notification-meta">
              <span className="notification-icon">
                <Users size={18} />
              </span>
              <strong>{item.patient_name}</strong>
              {!item.read_at && (
                <span className="notification-dot" aria-label="Unread" />
              )}
            </div>
            <p>{item.body}</p>
            <small>
              {new Date(item.created_at).toLocaleString([], {
                month: "short",
                day: "numeric",
                hour: "2-digit",
                minute: "2-digit",
              })}
            </small>
            <button
              className="text-button"
              onClick={async () => {
                try {
                  await api(`/care/notifications/${item.id}/read`, {
                    method: "POST",
                  });
                  setItems(
                    items.map((value) =>
                      value.id === item.id
                        ? { ...value, read_at: new Date().toISOString() }
                        : value,
                    ),
                  );
                  onOpen(item.report_id);
                } catch (e) {
                  setError((e as Error).message);
                }
              }}
            >
              Open current medicine records <CaretRight size={14} />
            </button>
          </article>
        ))
      )}
    </section>
  );
}

function ReminderWatcher({ accountId }: { accountId: string }) {
  useEffect(() => {
    let active = true;
    const shown = new Set<string>();
    const poll = async () => {
      if (document.visibilityState !== "visible") return;
      try {
        const values = await api<Reminder[]>("/reminders");
        if (
          !active ||
          !("Notification" in window) ||
          Notification.permission !== "granted" ||
          localStorage.getItem(`aftercare-alerts-${accountId}`) !== "on"
        )
          return;
        for (const item of values.filter((value) => value.alerting)) {
          const key = `${item.schedule_id}:${item.due_at}:${item.alert_at}`;
          if (shown.has(key) || sessionStorage.getItem(key)) continue;
          const registration =
            await navigator.serviceWorker?.getRegistration("/");
          const options = {
            body: "A care reminder is ready. Open AfterCare to check the current instructions.",
            tag: `${item.schedule_id}:${item.due_at}`,
          };
          if (registration)
            await registration.showNotification("AfterCare reminder", options);
          else new Notification("AfterCare reminder", options);
          shown.add(key);
          sessionStorage.setItem(key, "1");
        }
      } catch {
        /* The due list remains available after connectivity returns. */
      }
    };
    void poll();
    const timer = window.setInterval(poll, 15000);
    window.addEventListener("focus", poll);
    return () => {
      active = false;
      clearInterval(timer);
      window.removeEventListener("focus", poll);
    };
  }, [accountId]);
  return null;
}

function ReminderControls({ accountId }: { accountId: string }) {
  const [items, setItems] = useState<Reminder[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [enabled, setEnabled] = useState(
    localStorage.getItem(`aftercare-alerts-${accountId}`) === "on",
  );
  useEffect(() => {
    let active = true;
    const load = () =>
      api<Reminder[]>("/reminders")
        .then((values) => {
          if (active) {
            setItems(values);
            setLoaded(true);
            setLoadError("");
          }
        })
        .catch((e) => {
          if (active) setLoadError(e.message);
        });
    void load();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, 15000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);
  async function enable() {
    setBusy(true);
    setMessage("");
    try {
      if (!("Notification" in window) || !window.isSecureContext)
        throw new Error(
          "This browser does not support notifications here. The due list remains available in the app.",
        );
      if ((await Notification.requestPermission()) !== "granted")
        throw new Error(
          "Notifications are blocked. Change this site's notification permission in your browser settings to enable them.",
        );
      localStorage.setItem(`aftercare-alerts-${accountId}`, "on");
      setEnabled(true);
      const config = await api<{ configured: boolean; public_key: string }>(
        "/push/settings",
      );
      if (
        !config.configured ||
        !("serviceWorker" in navigator) ||
        !("PushManager" in window)
      ) {
        setMessage(
          "Alerts enabled while this app is open. Background alerts are unavailable here. Reminders still appear while this app is open.",
        );
        return;
      }
      const registration =
        await navigator.serviceWorker.register("/aftercare-sw.js");
      await navigator.serviceWorker.ready;
      const key = Uint8Array.from(
        atob(config.public_key.replaceAll("-", "+").replaceAll("_", "/")),
        (char) => char.charCodeAt(0),
      );
      let previous = await registration.pushManager.getSubscription();
      if (
        previous?.options.applicationServerKey &&
        Array.from(
          new Uint8Array(previous.options.applicationServerKey),
        ).join() !== Array.from(key).join()
      ) {
        await previous.unsubscribe();
        previous = null;
      }
      const subscription =
        previous ||
        (await registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: key,
        }));
      const device = await api<{ id: string }>(
        "/push/devices",
        jsonRequest("POST", subscription.toJSON()),
      );
      localStorage.setItem(`aftercare-push-${accountId}`, device.id);
      setMessage(
        "Background push enabled for this browser. Delivery needs this server running, internet access and browser/OS permission; delays are possible.",
      );
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function disable() {
    setBusy(true);
    try {
      const id = localStorage.getItem(`aftercare-push-${accountId}`);
      if (id) await api(`/push/devices/${id}`, { method: "DELETE" });
      localStorage.removeItem(`aftercare-push-${accountId}`);
      localStorage.removeItem(`aftercare-alerts-${accountId}`);
      setEnabled(false);
      setMessage("Notifications disabled for this account on this browser.");
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const doses = items.filter((item) => item.kind !== "care");
  return (
    <div className="reminder-controls">
      <section className="notification-settings">
        <div className="notification-meta">
          <span className="notification-icon">
            <BellSimple size={22} />
          </span>
          <div className="notification-copy">
            <strong>Browser notifications</strong>
            <p>Medicine reminders on this device</p>
          </div>
          <span className={`notification-status ${enabled ? "is-on" : ""}`}>
            {enabled ? "On" : "Off"}
          </span>
        </div>
        <button
          className={enabled ? "secondary wide" : "primary wide"}
          disabled={busy}
          onClick={enabled ? disable : enable}
        >
          {busy
            ? "Please wait…"
            : enabled
              ? "Turn off notifications"
              : "Enable notifications"}
        </button>
        {message && (
          <p role="status" className="notification-message">
            {message}
          </p>
        )}
        <details className="notification-details">
          <summary>How reminders work</summary>
          <p>
            Only confirmed, unchanged plans send alerts. Lock-screen messages
            hide patient and medicine details.
          </p>
          <p>
            Alerts prompt you to check your plan. Follow your clinician's advice
            for missed doses. A running server is required; background alerts
            also need internet and browser permission.
          </p>
          {enabled && (
            <button className="text-button" disabled={busy} onClick={enable}>
              Check background connection <CaretRight size={14} />
            </button>
          )}
        </details>
      </section>
      <SectionHeading title="Today's reminders" />
      {loadError ? (
        <p role="alert" className="notification-message">
          The due list could not be refreshed: {loadError}
        </p>
      ) : !loaded ? (
        <p role="status">Loading your reminders…</p>
      ) : doses.length ? (
        <div className="notification-list">
          {doses.map((i) => (
            <article
              className="notification-card"
              key={`${i.schedule_id}:${i.due_at}`}
            >
              <span className="notification-icon">
                <Pill size={20} />
              </span>
              <div className="notification-copy">
                <strong>{i.name}</strong>
                <p>
                  {i.dose}
                  {i.demo ? " · Fictional demo" : ""}
                </p>
                <small>
                  {i.alerting ? "Due for confirmation" : "Scheduled reminder"}
                </small>
              </div>
              <time dateTime={i.due_at}>
                {new Date(i.due_at).toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </time>
            </article>
          ))}
        </div>
      ) : (
        <div className="notification-empty">
          <span className="notification-icon">
            <CheckCircle size={22} />
          </span>
          <div>
            <strong>No pending reminders</strong>
            <p>Pending doses from your active plans appear here.</p>
          </div>
        </div>
      )}
    </div>
  );
}

function RecoveryApp({
  account,
  signOut,
}: {
  account: Account;
  signOut: () => Promise<void>;
}) {
  const [screen, setScreen] = useState<Screen>("Home");
  const [allReports, setReports] = useState<Report[]>([]);
  const [newManualReminder, setNewManualReminder] = useState("");
  const [archives, setArchives] = useState<ArchivedReport[]>([]);
  const [deleting, setDeleting] = useState<ArchivedReport | null>(null);
  const [deleteName, setDeleteName] = useState("");
  const [deletePassword, setDeletePassword] = useState("");
  const [managedReport, setManagedReport] = useState<Report | null>(null);
  const [confirmArchive, setConfirmArchive] = useState(false);
  const [workspace, setWorkspace] = useState<Workspace>({
    patients: [],
    legacy_count: 0,
    invitations: [],
  });
  const [inviteUsername, setInviteUsername] = useState("");
  const [inviteAlerts, setInviteAlerts] = useState<AlertPreferences>({
    taken: true,
    skipped: true,
    unconfirmed: true,
    delay_minutes: 30,
  });
  const [inviteRole, setInviteRole] = useState<"viewer" | "recorder">("viewer");
  const [accessHistory, setAccessHistory] = useState<CareAudit[]>([]);
  const [patientId, setPatientId] = useState("");
  const [episodeId, setEpisodeId] = useState("");
  const [careMode, setCareMode] = useState<
    "patient" | "episode" | "contact" | null
  >(null);
  const [careName, setCareName] = useState("");
  const [started, setStarted] = useState(() =>
    new Intl.DateTimeFormat("en-CA", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(new Date()),
  );
  const [contactRole, setContactRole] = useState("");
  const [phone, setPhone] = useState("");
  const [contactNote, setContactNote] = useState("");
  const patient = workspace.patients.find((p) => p.id === patientId);
  const isOwner = patient?.access_role === "owner";
  const canRecord = isOwner || patient?.access_role === "recorder";
  const episode = patient?.episodes.find((e) => e.id === episodeId);
  const reports = allReports.filter((r) => r.episode_id === episodeId);
  const patientReports = allReports.filter((r) =>
    patient?.episodes.some((e) => e.id === r.episode_id),
  );
  const allMedicines = savedMedicines(patientReports);
  const medicineReports = patientReports.filter(
    (item) => medicines(item).length > 0,
  );
  const contactFields = reports.flatMap((item) =>
    item.fields
      .filter(
        (field) => field.group === "Contacts" && field.status !== "rejected",
      )
      .map((field) => ({ report: item, field })),
  );
  const activeShares =
    patient?.sharing.filter(
      (share) => share.status === "active" || share.status === "pending",
    ) || [];
  const [report, setReport] = useState<Report | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [reading, setReading] = useState(false);
  const [sheet, setSheet] = useState<
    | "manual-visit"
    | "manual-medicine"
    | "routine"
    | "delete-report"
    | "report-options"
    | "archives"
    | "sharing"
    | "access-history"
    | "care"
    | "account"
    | "security"
    | "record-medication"
    | "legacy-import"
    | "questions"
    | "upload"
    | "about"
    | "updates"
    | "history"
    | "medication"
    | "visit"
    | null
  >(null);
  const [securityPassword, setSecurityPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [recoveryCode, setRecoveryCode] = useState("");
  const [recoveryCopyMessage, setRecoveryCopyMessage] = useState("");
  const [recoveryConfigured, setRecoveryConfigured] = useState(false);
  useEffect(() => {
    if (sheet !== "archives") {
      setDeleting(null);
      setDeleteName("");
      setDeletePassword("");
    }
    if (sheet !== "security") {
      setSecurityPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setRecoveryCode("");
      setRecoveryCopyMessage("");
    }
  }, [sheet]);
  const [ocrAvailable, setOcrAvailable] = useState(false);
  const [activity, setActivity] = useState<Activity>({
    medications: [],
    visits: [],
  });
  const [activityLoadError, setActivityLoadError] = useState(false);
  const [now, setNow] = useState(() => new Date());
  const [medicationGroup, setMedicationGroup] = useState("");
  const [activityNote, setActivityNote] = useState("");
  const [visitField, setVisitField] = useState<CareField | null>(null);
  const [bookingDate, setBookingDate] = useState({
    day: "",
    month: "",
    year: "",
  });
  const visitDate =
    bookingDate.year && bookingDate.month && bookingDate.day
      ? `${bookingDate.year}-${bookingDate.month}-${bookingDate.day}`
      : "";
  const [query, setQuery] = useState("");
  const [history, setHistory] = useState<
    { id: number; after: string; created: string }[]
  >([]);
  const input = useRef<HTMLInputElement>(null);
  const logRequest = useRef<{ id: string; signature: string } | null>(null);
  const keyboard = useKeyboard();
  const { bottomInset } = useKeyboardInsets();
  const meds = medicines(report);
  const medicineReport =
    medicineReports.find((item) => item.id === report?.id) ||
    medicineReports[0];
  useEffect(() => {
    if (screen === "Meds" && medicineReport && medicineReport.id !== report?.id)
      setReport(medicineReport);
  }, [screen, medicineReport?.id, report?.id]);
  const selectedMedication = meds.find((med) => med.group === medicationGroup);
  const pending =
    report?.fields.filter((f) => f.status === "pending").length || 0;
  const name = patient?.name.split(" ")[0];
  const today = new Intl.DateTimeFormat("en-CA").format(now);
  const summary = careSummary(report, activity, today);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 60000);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    Promise.all([
      api<Workspace>("/care/personal", { method: "POST" }),
      api<Report[]>("/reports"),
    ])
      .then(async ([care, items]) => {
        setWorkspace(care);
        setReports(items);
        const personal = care.personal;
        const self =
          care.patients.find((p) => p.id === personal?.patient_id) ||
          care.patients.find((p) => p.access_role === "owner");
        const shared = care.patients.find((p) => p.access_role !== "owner");
        const owner =
          self?.episodes.some((e) =>
            items.some((r) => r.episode_id === e.id),
          ) || !shared
            ? self
            : shared;
        const selected =
          owner?.episodes.find((e) => e.id === personal?.episode_id) ||
          owner?.episodes[0];
        setPatientId(owner?.id || "");
        setEpisodeId(selected?.id || "");
        setReport(items.find((r) => r.episode_id === selected?.id) || null);
      })
      .catch((e) => setError(e.message));
    api<{ models: string[]; model: string; ocr_available: boolean }>("/health")
      .then((h) => {
        setOcrAvailable(h.ocr_available);
      })
      .catch(() => {});
  }, []);
  useEffect(() => {
    setActivity({ medications: [], visits: [] });
    setActivityLoadError(false);
    if (!report?.id) return;
    let cancelled = false;
    api<Activity>(`/reports/${report.id}/activity`)
      .then((result) => {
        if (!cancelled) {
          setActivity(result);
        }
      })
      .catch(() => {
        if (!cancelled) setActivityLoadError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [report?.id]);
  useEffect(() => {
    let cancelled = false;
    async function checkAccess() {
      if (document.visibilityState !== "visible") return;
      try {
        const [next, items] = await Promise.all([
          api<Workspace>("/care"),
          api<Report[]>("/reports"),
        ]);
        if (cancelled) return;
        setWorkspace(next);
        setReports(items);
        const selected = next.patients.find((p) => p.id === patientId);
        if (
          patientId &&
          (!selected || selected.access_role !== patient?.access_role)
        ) {
          keyboard.hide();
          setSheet(null);
          setActivity({ medications: [], visits: [] });
          setReport(null);
          setReports([]);
          if (!selected) {
            setPatientId("");
            setEpisodeId("");
          }
          setScreen("Family");
          setNotice(
            "Your access changed. Refresh your care circle to load the records you can access.",
          );
        } else if (report && !items.some((item) => item.id === report.id)) {
          keyboard.hide();
          setManagedReport(null);
          setSheet(null);
          setReport(null);
          setActivity({ medications: [], visits: [] });
          setScreen("Reports");
          setNotice(
            "This report is no longer available. It may have been archived by its owner.",
          );
        }
      } catch {
        /* The next user action reports connection or session errors. */
      }
    }
    window.addEventListener("focus", checkAccess);
    const timer = window.setInterval(checkAccess, 30000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      window.removeEventListener("focus", checkAccess);
    };
  }, [patientId, patient?.access_role, report?.id]);

  async function refreshWorkspace(next?: Workspace, preferredPatient?: string) {
    const care = next || (await api<Workspace>("/care"));
    const items = await api<Report[]>("/reports");
    const selected =
      care.patients.find((p) => p.id === (preferredPatient || patientId)) ||
      care.patients[0];
    const selectedEpisode =
      selected?.episodes.find((e) => e.id === episodeId) ||
      selected?.episodes[0];
    const selectedReport =
      items.find(
        (r) => r.id === report?.id && r.episode_id === selectedEpisode?.id,
      ) ||
      items.find((r) => r.episode_id === selectedEpisode?.id) ||
      null;
    setWorkspace(care);
    setReports(items);
    setReport(selectedReport);
    setPatientId(selected?.id || "");
    setEpisodeId(selectedEpisode?.id || "");
    setActivity(
      selectedReport
        ? await api<Activity>(`/reports/${selectedReport.id}/activity`)
        : { medications: [], visits: [] },
    );
  }
  async function inviteCaregiver(event: React.FormEvent) {
    event.preventDefault();
    keyboard.hide();
    await run(async () => {
      setWorkspace(
        await api<Workspace>(
          `/care/patients/${patientId}/invitations`,
          jsonRequest("POST", {
            username: inviteUsername,
            role: inviteRole,
            ...inviteAlerts,
          }),
        ),
      );
      setSheet(null);
      setInviteUsername("");
      setNotice(
        "Invitation created. Access starts only after this person accepts.",
      );
    });
  }
  async function respondToInvite(id: string, action: "accept" | "decline") {
    await run(async () => {
      const next = await api<Workspace>(
        `/care/invitations/${id}/respond`,
        jsonRequest("POST", { action }),
      );
      const added = next.patients.find(
        (p) => !workspace.patients.some((old) => old.id === p.id),
      );
      await refreshWorkspace(next, added?.id);
      setNotice(
        action === "accept"
          ? "Invitation accepted. Your permissions are shown with the patient profile."
          : "Invitation declined.",
      );
    });
  }
  function openSharedReport(id: string) {
    const next = allReports.find((item) => item.id === id);
    const owner = workspace.patients.find((patient) =>
      patient.episodes.some((episode) => episode.id === next?.episode_id),
    );
    if (next && owner) {
      chooseEpisode(owner.id, next.episode_id);
      acceptReport(next);
      setSheet(null);
      navigate("Meds");
    } else
      setError(
        "This prescription is no longer available. Refresh your care circle.",
      );
  }
  async function openAccessHistory() {
    await run(async () => {
      setAccessHistory(
        await api<CareAudit[]>(`/care/patients/${patientId}/access-history`),
      );
      keyboard.hide();
      setSheet("access-history");
    });
  }
  function chooseEpisode(nextPatient: string, nextEpisode: string) {
    keyboard.hide();
    setPatientId(nextPatient);
    setEpisodeId(nextEpisode);
    sessionStorage.setItem(`aftercare-episode-${account.id}`, nextEpisode);
    setReport(allReports.find((r) => r.episode_id === nextEpisode) || null);
    setActivity({ medications: [], visits: [] });
    setError("");
    setNotice("");
    setScreen("Home");
    setCareMode(null);
  }
  function openCare(mode: typeof careMode = null) {
    keyboard.hide();
    setCareMode(mode);
    setCareName("");
    setPhone("");
    setContactRole("");
    setContactNote("");
    setSheet("care");
  }
  function openUpload() {
    if (patient && !isOwner) {
      setError("Only the profile owner can add reports.");
      return;
    }
    if (!episodeId) openCare(patient ? "episode" : "patient");
    else setSheet("upload");
  }
  async function saveCare(event: React.FormEvent) {
    event.preventDefault();
    keyboard.hide();
    await run(async () => {
      const path =
        careMode === "patient"
          ? "/care/patients"
          : `/care/patients/${patientId}/${careMode === "episode" ? "episodes" : "contacts"}`;
      const body =
        careMode === "patient"
          ? { name: careName }
          : careMode === "episode"
            ? { title: careName, started }
            : { name: careName, role: contactRole, phone, note: contactNote };
      const next = await api<Workspace>(path, jsonRequest("POST", body));
      setWorkspace(next);
      if (careMode === "patient") {
        const added = next.patients.find(
          (p) => !workspace.patients.some((old) => old.id === p.id),
        )!;
        chooseEpisode(added.id, "");
        setCareMode("episode");
      } else if (careMode === "episode") {
        const added = next.patients
          .find((p) => p.id === patientId)!
          .episodes.find(
            (e) => !patient?.episodes.some((old) => old.id === e.id),
          )!;
        chooseEpisode(patientId, added.id);
        setSheet(null);
      } else {
        setCareMode(null);
        setSheet(null);
      }
      setCareName("");
    });
  }
  async function importLocal() {
    await run(async () => {
      setWorkspace(
        await api<Workspace>(`/care/episodes/${episodeId}/import-local`, {
          method: "POST",
        }),
      );
      const items = await api<Report[]>("/reports");
      setReports(items);
      setReport(items.find((r) => r.episode_id === episodeId) || null);
      setSheet(null);
      setNotice("Previous local reports imported into this recovery episode.");
    });
  }
  function navigate(next: Screen) {
    keyboard.hide();
    setError("");
    setNotice("");
    setScreen(next);
  }
  function acceptReport(next: Report) {
    setReport(next);
    setReports((items) => [
      next,
      ...items.filter((item) => item.id !== next.id),
    ]);
  }
  function manageReport(item: Report) {
    keyboard.hide();
    setError("");
    setManagedReport(item);
    setConfirmArchive(false);
    setSheet("report-options");
  }
  async function openArchives() {
    await run(async () => {
      setArchives(await api<ArchivedReport[]>("/reports/archived"));
      setSheet("archives");
    });
  }
  async function archiveReport() {
    if (!managedReport) return;
    await run(async () => {
      await api(`/reports/${managedReport.id}/archive`, { method: "POST" });
      setReports((items) =>
        items.filter((item) => item.id !== managedReport.id),
      );
      if (report?.id === managedReport.id) {
        setReport(null);
        setActivity({ medications: [], visits: [] });
      }
      setSheet(null);
      setManagedReport(null);
      await refreshWorkspace();
      setNotice("Report archived. You can restore it from Archived reports.");
    });
  }
  async function restoreReport(item: ArchivedReport) {
    await run(async () => {
      const restored = await api<Report>(`/reports/${item.id}/restore`, {
        method: "POST",
      });
      acceptReport(restored);
      setSheet(null);
      setScreen("Reports");
      setNotice(
        "Report restored with its original file, reviews and care records.",
      );
    });
  }
  async function run(task: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await task();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }
  async function loadSample(kind = "pdf") {
    setSheet(null);
    setReading(true);
    await run(async () => {
      acceptReport(
        await api<Report>(
          `/reports/sample?kind=${kind}&episode_id=${episodeId}`,
          {
            method: "POST",
          },
        ),
      );
      navigate("Review");
    });
    setReading(false);
  }
  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setSheet(null);
    setReading(true);
    await run(async () => {
      const body = new FormData();
      body.append("file", file);
      acceptReport(
        await api<Report>(`/reports?episode_id=${episodeId}`, {
          method: "POST",
          body,
        }),
      );
      navigate("Review");
    });
    event.target.value = "";
    setReading(false);
  }
  function select(_field: CareField) {
    keyboard.hide();
  }
  function openReview(_field?: CareField) {
    keyboard.hide();
    setSheet(null);
    navigate("Review");
  }
  async function refreshToday() {
    if (!report) return;
    await run(async () => {
      const [current, records] = await Promise.all([
        api<Report>(`/reports/${report.id}`),
        api<Activity>(`/reports/${report.id}/activity`),
      ]);
      acceptReport(current);
      setActivity(records);
      setActivityLoadError(false);
      setNow(new Date());
      setNotice("Report and care activity refreshed.");
    });
  }
  async function openSecurity() {
    keyboard.hide();
    await run(async () => {
      const security = await api<{ recovery_configured: boolean }>(
        "/auth/security",
      );
      setRecoveryConfigured(security.recovery_configured);
      setSheet("security");
    });
  }
  async function generateRecovery() {
    keyboard.hide();
    await run(async () => {
      const result = await api<{ recovery_code: string }>(
        "/auth/recovery-code",
        jsonRequest("POST", { current_password: securityPassword }),
      );
      setRecoveryCode(result.recovery_code);
      setRecoveryCopyMessage("");
      setRecoveryConfigured(true);
      setSecurityPassword("");
    });
  }
  async function changePassword(event: React.FormEvent) {
    event.preventDefault();
    keyboard.hide();
    if (newPassword !== confirmPassword) {
      setError("The new passwords do not match.");
      return;
    }
    await run(async () => {
      await api(
        "/auth/password",
        jsonRequest("POST", {
          current_password: securityPassword,
          new_password: newPassword,
        }),
      );
      setSecurityPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setRecoveryCode("");
      setRecoveryConfigured(false);
      setNotice(
        "Password changed. Other sessions and the old recovery code were revoked. Create a new recovery code.",
      );
      setSheet("account");
    });
  }
  async function openHistory(reportId: string) {
    keyboard.hide();
    await run(async () => {
      setHistory(await api(`/reports/${reportId}/history`));
      setSheet("history");
    });
  }
  function openMedication(group: string) {
    keyboard.hide();
    setError("");
    logRequest.current = null;
    setMedicationGroup(group);
    setActivityNote("");
    setSheet("medication");
  }
  async function logMedication(status: "taken" | "skipped") {
    if (!report || !selectedMedication) return;
    keyboard.hide();
    const signature = JSON.stringify([
      report.id,
      medicationGroup,
      status,
      activityNote,
    ]);
    if (logRequest.current?.signature !== signature)
      logRequest.current = { id: crypto.randomUUID(), signature };
    const requestId = logRequest.current.id;
    await run(async () => {
      const result = await api<Activity>(
        `/reports/${report.id}/medications/log`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            request_id: requestId,
            group: medicationGroup,
            status,
            note: activityNote,
          }),
        },
      );
      setActivity(result);
      setSheet(null);
      keyboard.hide();
      logRequest.current = null;
      setNotice(`${selectedMedication.name}: ${status} recorded.`);
    });
  }
  async function undoMedication(id: string) {
    if (!report) return;
    await run(async () => {
      setActivity(
        await api<Activity>(
          `/reports/${report.id}/medications/log/${id}/undo`,
          { method: "POST" },
        ),
      );
      setNotice("Medication record undone.");
    });
  }
  function openVisit(
    field: CareField,
    source?: Report,
    savedVisit?: Visit | null,
  ) {
    keyboard.hide();
    setError("");
    if (source) acceptReport(source);
    setVisitField(field);
    const visit =
      savedVisit === undefined
        ? activity.visits.find((v) => v.field_id === field.id)
        : savedVisit;
    const [year = "", month = "", day = ""] = (visit?.planned_date || "").split(
      "-",
    );
    setBookingDate({ year, month, day });
    setActivityNote(visit?.note || "");
    setSheet("visit");
  }
  async function saveVisit(status: Visit["status"]) {
    if (!report || !visitField) return;
    keyboard.hide();
    await run(async () => {
      setActivity(
        await api<Activity>(`/reports/${report.id}/visits/${visitField.id}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            status,
            planned_date: status === "planned" ? null : visitDate || null,
            note: activityNote,
          }),
        }),
      );
      setSheet(null);
      keyboard.hide();
      window.dispatchEvent(new Event("aftercare-visits-updated"));
      setNotice(
        status === "completed"
          ? "Marked as completed."
          : status === "booked"
            ? "Booking saved."
            : "Booking cleared.",
      );
    });
  }
  function changeBookingDate(part: "day" | "month" | "year", value: string) {
    const next = { ...bookingDate, [part]: value };
    const days = new Date(
      Number(next.year) || new Date().getFullYear(),
      Number(next.month) || 1,
      0,
    ).getDate();
    if (Number(next.day) > days) next.day = "";
    setBookingDate(next);
  }
  function medicationCard(
    med: ReturnType<typeof medicines>[number],
    index: number,
    source: Report,
  ) {
    const recordsToday = (
      source.id === report?.id ? activity.medications : []
    ).filter(
      (entry) =>
        entry.medication_group === med.group &&
        new Date(entry.occurred_at).toDateString() ===
          new Date().toDateString(),
    ).length;
    return (
      <button
        className="med-card"
        key={`${source.id}:${med.group}`}
        onClick={() => {
          acceptReport(source);
          openMedication(med.group);
        }}
      >
        <div className={`med-symbol shade-${index % 2}`}>
          <Pill size={24} weight="duotone" />
        </div>
        <div className="med-copy">
          <strong>{med.name}</strong>
          <span>
            {med.strength || "Strength not stated"} ·{" "}
            {med.frequency || "Frequency not stated"}
          </span>
          {source.kind !== "manual" && (
            <small className="medicine-origin">{source.name}</small>
          )}
        </div>
        <CaretRight size={17} />
        <div className="med-card-footer">
          <span className={`small-badge ${med.reviewed ? "green" : "amber"}`}>
            {med.reviewed ? <ShieldCheck /> : <Info />}
            {med.reviewed
              ? source.kind === "manual"
                ? isOwner
                  ? "Added by you"
                  : "Manually added"
                : "Transcription reviewed"
              : "Check details"}
          </span>
          <span>
            {recordsToday
              ? `${recordsToday} ${recordsToday === 1 ? "record" : "records"} today`
              : "View details"}
          </span>
        </div>
      </button>
    );
  }
  function recentActivity(group?: string) {
    const entries = activity.medications
      .filter((entry) => !group || entry.medication_group === group)
      .slice(0, 10);
    return entries.length ? (
      <div className="activity-list">
        {entries.map((entry) => (
          <div className="activity-row" key={entry.id}>
            <div className={`activity-icon ${entry.status}`}>
              {entry.status === "taken" ? <Check size={17} /> : <X size={17} />}
            </div>
            <div>
              <strong>{entry.snapshot.Name || entry.medication_group}</strong>
              <span>
                {entry.status === "taken" ? "Taken" : "Skipped"} ·{" "}
                {new Date(entry.occurred_at).toLocaleString("en-IN", {
                  day: "numeric",
                  month: "short",
                  hour: "numeric",
                  minute: "2-digit",
                })}
              </span>
              <span>
                Recorded by{" "}
                {entry.actor_name || "earlier record (author unavailable)"}
              </span>
              {entry.note && <p>{entry.note}</p>}
            </div>
            {(isOwner || (canRecord && entry.actor_id === account.id)) && (
              <button
                className="text-button"
                disabled={busy}
                aria-label={`Undo ${entry.snapshot.Name || entry.medication_group} ${entry.status} record`}
                onClick={() => undoMedication(entry.id)}
              >
                Undo
              </button>
            )}
          </div>
        ))}
      </div>
    ) : (
      <p className="activity-empty">No medication activity recorded yet.</p>
    );
  }
  return (
    <MotionConfig reducedMotion="user">
      <div className="aftercare-app">
        <ReminderWatcher accountId={account.id} />
        <header className="app-header">
          {screen === "Home" ? (
            <div className="greeting">
              <button
                className="avatar"
                aria-label="Account settings"
                onClick={() => {
                  keyboard.hide();
                  setSheet("account");
                }}
              >
                {name?.slice(0, 1) || "A"}
              </button>
              <div>
                <strong>
                  {name === "Me"
                    ? "Your daily care"
                    : name
                      ? isOwner
                        ? `Hey, ${name}`
                        : `Caring for ${name}`
                      : "Hello, there"}
                  <span className="greeting-dot" />
                </strong>
                <small>
                  {patient && !isOwner
                    ? `Shared by ${patient.owner_username}`
                    : "A little care, every day."}
                </small>
              </div>
            </div>
          ) : (
            <>
              <button
                className="icon-button"
                aria-label="Back home"
                onClick={() => navigate("Home")}
              >
                <ArrowLeft size={19} />
              </button>
              <strong>{screenTitles[screen]}</strong>
            </>
          )}
          <div className="header-actions">
            {screen !== "Home" && (
              <button
                className="icon-button"
                aria-label="Account settings"
                onClick={() => {
                  keyboard.hide();
                  setSheet("account");
                }}
              >
                <UserCircle size={21} />
              </button>
            )}
            {screen === "Home" && (
              <button
                className="icon-button notification-button"
                aria-label="Reminders and updates"
                onClick={() => {
                  keyboard.hide();
                  setSheet("updates");
                }}
              >
                <BellSimple size={20} />
                {workspace.invitations.length > 0 && <i />}
              </button>
            )}
          </div>
        </header>
        <MobileScroll className="aftercare-scroll" key={screen}>
          <main className={`care-content screen-${screen.toLowerCase()}`}>
            {notice && (
              <div className="success-banner" role="status">
                <CheckCircle size={19} />
                <span>{notice}</span>
                <button
                  aria-label="Dismiss update"
                  onClick={() => setNotice("")}
                >
                  <X size={15} />
                </button>
              </div>
            )}
            {error && (
              <div className="error-banner" role="alert">
                <WarningCircle size={20} />
                <span>{error}</span>
                <button aria-label="Dismiss error" onClick={() => setError("")}>
                  <X size={15} />
                </button>
              </div>
            )}
            {reading && (
              <div className="plain-card reading-status" role="status">
                <Sparkle size={24} />
                <h3>Reading your prescription</h3>
                <p>
                  Text and instructions are processed on this installation. This
                  can take a moment.
                </p>
              </div>
            )}
            {activityLoadError &&
              ["Meds", "Visits", "Family"].includes(screen) && (
                <div className="error-banner" role="alert">
                  Recent care records could not be loaded.
                  <button
                    className="text-button"
                    disabled={busy}
                    onClick={refreshToday}
                  >
                    Refresh
                  </button>
                </div>
              )}
            {screen === "Home" && (
              <>
                {patient?.access_role !== "owner" && patient && (
                  <p className="viewing-care">
                    <ShieldCheck size={16} />
                    {canRecord
                      ? "Can view and record care"
                      : "View-only access"}{" "}
                    <button
                      className="text-button"
                      onClick={() => {
                        const own = workspace.patients.find(
                          (p) => p.access_role === "owner",
                        );
                        if (own?.episodes[0])
                          chooseEpisode(own.id, own.episodes[0].id);
                      }}
                    >
                      Back to my medicines
                    </button>
                  </p>
                )}
                {(workspace.invitations.length > 0 ||
                  (isOwner &&
                    workspace.patients.some(
                      (p) => p.access_role !== "owner",
                    )) ||
                  workspace.patients.filter((p) => p.access_role !== "owner")
                    .length > 1) && (
                  <button
                    className="shared-journey-shortcut"
                    onClick={() => navigate("Family")}
                  >
                    <Users size={21} />
                    <span>
                      {workspace.invitations.length
                        ? `${workspace.invitations.length} care invitation${workspace.invitations.length === 1 ? "" : "s"} waiting`
                        : "People you support"}
                    </span>
                    <CaretRight size={17} />
                  </button>
                )}
                <HomeCare
                  patientId={patientId}
                  patientName={patient?.name || "Your person"}
                  canRecord={!!canRecord}
                  isOwner={!!isOwner}
                  onAdd={openUpload}
                  hasPrescription={medicineReports.length > 0}
                  pendingReport={reports.find((item) => !item.plan_saved)}
                  onReview={() => {
                    const next = reports.find((item) => !item.plan_saved);
                    if (next) acceptReport(next);
                    navigate("Review");
                  }}
                  onMeds={(id?: string) => {
                    const next = allReports.find((item) => item.id === id);
                    if (next) {
                      acceptReport(next);
                      setEpisodeId(next.episode_id);
                    }
                    navigate("Meds");
                  }}
                />
                {patient && !isOwner && (
                  <CareUpdates
                    onOpen={openSharedReport}
                    patientId={patientId}
                  />
                )}
                <div className="home-shortcuts">
                  <button
                    className="text-button"
                    onClick={() => navigate("Visits")}
                  >
                    <CalendarBlank size={17} />
                    Visits & tests
                  </button>
                  <button
                    className="text-button"
                    onClick={() => navigate("Family")}
                  >
                    <Users size={17} />
                    Contacts & care circle
                  </button>
                </div>
              </>
            )}
            {screen === "Reports" && (
              <>
                <h1>
                  A home for your
                  <br />
                  health documents.
                </h1>
                <p className="intro">
                  From discharge to your next appointment.
                </p>
                <button
                  className="upload-card"
                  disabled={!isOwner || busy}
                  onClick={openUpload}
                >
                  <div className="round-icon">
                    <UploadSimple size={26} />
                  </div>
                  <strong>Add prescription or report</strong>
                  <span>PDF, JPG or PNG · Up to 12 MB</span>
                  <span className="upload-link">
                    Choose a file <Plus size={17} />
                  </span>
                </button>
                <SectionHeading title="Your documents" />
                {reports.map((item) => (
                  <div className="document-entry" key={item.id}>
                    <button
                      className="document-card"
                      disabled={busy}
                      onClick={() => {
                        acceptReport(item);
                        navigate("Review");
                      }}
                    >
                      <div className="round-icon">
                        <FileText size={25} />
                      </div>
                      <div>
                        <strong>
                          {item.sample ? "Discharge summary" : item.name}
                        </strong>
                        <span>
                          {new Date(item.created).toLocaleDateString("en-IN", {
                            day: "numeric",
                            month: "short",
                          })}{" "}
                          ·{" "}
                          {item.kind === "manual"
                            ? isOwner
                              ? "Added by you · No document"
                              : "Manual entry · No document"
                            : item.sample
                              ? "Fictional sample"
                              : "Local document"}
                        </span>
                        <span
                          className={`small-badge ${item.plan_saved ? "green" : "amber"}`}
                        >
                          {item.plan_saved ? "Plan saved" : "Review required"}
                        </span>
                      </div>
                      {!isOwner && <CaretRight />}
                    </button>
                    {isOwner && (
                      <button
                        className="icon-button document-options"
                        aria-label={`Manage ${item.name}`}
                        disabled={busy}
                        onClick={() => manageReport(item)}
                      >
                        <DotsThree size={23} weight="bold" />
                      </button>
                    )}
                  </div>
                ))}
                {!reports.length && (
                  <div className="empty-inline">
                    <FileText size={28} />
                    <p>
                      No documents yet.
                      <br />
                      Try a fictional report to explore.
                    </p>
                  </div>
                )}
                <button
                  className="secondary wide"
                  disabled={busy || !isOwner}
                  onClick={() => loadSample()}
                >
                  <Sparkle size={18} />
                  Try a fictional report
                </button>
                {isOwner && (
                  <button
                    className="secondary wide"
                    disabled={busy}
                    onClick={openArchives}
                  >
                    <Archive size={18} /> Archived reports
                  </button>
                )}
              </>
            )}
            {screen === "Meds" && (
              <>
                <h1>
                  The details,
                  <br />
                  all in one place.
                </h1>
                <p className="intro">
                  All your saved medicines, together with their source details.
                </p>
                {isOwner && (
                  <button className="secondary wide" onClick={openUpload}>
                    <Plus size={18} />
                    Add medicine or prescription
                  </button>
                )}
                {medicineReports.length > 1 && (
                  <label className="activity-label reminder-source-picker">
                    Manage reminders for
                    <CareSelect
                      label="Reminder prescription"
                      value={medicineReport?.id || ""}
                      onChange={(id) => {
                        const item = medicineReports.find((r) => r.id === id);
                        if (item) acceptReport(item);
                      }}
                      options={medicineReports.map((r) => ({
                        value: r.id,
                        label: r.name,
                      }))}
                    />
                  </label>
                )}
                {medicineReport && (
                  <SchedulePanel
                    key={medicineReport.id}
                    report={medicineReport}
                    isOwner={!!isOwner}
                    canRecord={!!canRecord}
                    initialSetup={newManualReminder === medicineReport.id}
                    onSetupHandled={() => setNewManualReminder("")}
                  />
                )}
                <label className="search-field">
                  <MagnifyingGlass size={20} />
                  <KeyboardInput
                    aria-label="Search medications"
                    placeholder="Find a medication"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    onBlur={() => keyboard.hide()}
                  />
                </label>
                {allMedicines
                  .filter(({ medicine }) =>
                    medicine.name.toLowerCase().includes(query.toLowerCase()),
                  )
                  .map(({ medicine, report: source }, index) =>
                    medicationCard(medicine, index, source),
                  )}
                {!allMedicines.length && (
                  <div className="empty-inline">
                    <Pill size={30} />
                    <p>
                      Add a medicine manually or upload a prescription to get
                      started.
                    </p>
                  </div>
                )}
                {!!allMedicines.length &&
                  !allMedicines.some(({ medicine }) =>
                    medicine.name.toLowerCase().includes(query.toLowerCase()),
                  ) && <p className="empty-inline">No matching medications.</p>}
                <div className="note">
                  <Info size={20} />
                  <p>
                    <strong>A record of what happened.</strong>{" "}
                    {canRecord
                      ? "Tap a medicine to record taken or skipped."
                      : "Your access is view only. Tap a medicine to inspect its details."}{" "}
                    Manual events and reminder doses are recorded separately.
                  </p>
                </div>
                <SectionHeading title="Recent activity" />
                {recentActivity()}
              </>
            )}
            {screen === "Visits" && (
              <VisitsPanel
                patientId={patientId}
                isOwner={!!isOwner}
                canRecord={!!canRecord}
                onAdd={() => {
                  keyboard.hide();
                  setSheet("manual-visit");
                }}
                onOpen={(item) => {
                  const source = allReports.find(
                    (r) => r.id === item.report_id,
                  );
                  if (source) openVisit(item.field, source, item.visit);
                  else
                    setError("Refresh your records before opening this visit.");
                }}
              />
            )}
            {screen === "Family" && (
              <div className="family-page">
                <h1>Your care circle.</h1>
                <p className="intro">
                  People you trust. Support when you need it.
                </p>
                <div className="care-person">
                  <span className="settings-avatar">
                    {(patient?.name || "?").slice(0, 1)}
                  </span>
                  <div>
                    <small>Care for</small>
                    <strong>{patient?.name || "Choose a profile"}</strong>
                  </div>
                  <button
                    className="icon-button"
                    aria-label="Refresh care circle"
                    disabled={busy}
                    onClick={() =>
                      run(async () => {
                        await refreshWorkspace();
                        setNotice("Care circle refreshed.");
                      })
                    }
                  >
                    <ArrowsClockwise size={20} />
                  </button>
                </div>
                {workspace.patients.some((p) => p.access_role !== "owner") && (
                  <section className="family-section">
                    <SectionHeading title="People you support" />
                    {workspace.patients
                      .filter((p) => p.access_role !== "owner")
                      .map((p) => (
                        <button
                          className="settings-row family-history"
                          key={p.id}
                          onClick={() =>
                            chooseEpisode(p.id, p.episodes[0]?.id || "")
                          }
                        >
                          <span className="settings-avatar">
                            {p.name.slice(0, 1)}
                          </span>
                          <span className="settings-row-copy">
                            <strong>{p.name}</strong>
                            <small>
                              Shared by {p.owner_username} ·{" "}
                              {p.access_role === "viewer"
                                ? "View only"
                                : "View and record care"}
                            </small>
                          </span>
                          <CaretRight size={17} />
                        </button>
                      ))}
                  </section>
                )}
                {!!workspace.invitations.length && (
                  <SectionHeading title="Invitations for you" />
                )}
                {workspace.invitations.map((invite) => (
                  <section
                    className="plain-card invitation-card"
                    key={invite.id}
                  >
                    <div className="person-heading">
                      <span className="settings-row-icon">
                        <Users size={21} />
                      </span>
                      <div>
                        <h2>{invite.patient_name}</h2>
                        <p>Invited by {invite.owner_username}</p>
                      </div>
                    </div>
                    <div className="member-labels">
                      <span className="small-badge amber">
                        Awaiting your response
                      </span>
                      <small>
                        Expires{" "}
                        {new Date(invite.expires_at).toLocaleDateString(
                          "en-IN",
                          { day: "numeric", month: "short" },
                        )}
                      </small>
                    </div>
                    <div className="permission-summary">
                      <ShieldCheck size={18} />
                      <strong>
                        {invite.role === "viewer"
                          ? "View only"
                          : "View and record care"}
                      </strong>
                    </div>
                    <ul className="permission-list">
                      <li>
                        View and download current and future documents, original
                        reports, reviewed plans, contacts and care activity.
                      </li>
                      {invite.role === "recorder" && (
                        <li>
                          Log medication events, undo your own entries and
                          update visits.
                        </li>
                      )}
                      <li>
                        Report editing, review and sharing stay with the owner.
                        Access continues until they revoke it.
                      </li>
                    </ul>
                    <div className="setup-actions">
                      <button
                        className="secondary"
                        disabled={busy}
                        onClick={() => respondToInvite(invite.id, "decline")}
                      >
                        Decline
                      </button>
                      <button
                        className="primary"
                        disabled={busy}
                        onClick={() => respondToInvite(invite.id, "accept")}
                      >
                        Accept invitation
                      </button>
                    </div>
                  </section>
                ))}
                {patient && (
                  <section className="family-section">
                    <SectionHeading title="Caregivers" />
                    {isOwner ? (
                      <>
                        {activeShares.length ? (
                          activeShares.map((share) => (
                            <article className="member-card" key={share.id}>
                              <div className="person-heading">
                                <span className="member-avatar">
                                  {share.username.slice(0, 1).toUpperCase()}
                                </span>
                                <div>
                                  <strong>{share.username}</strong>
                                  <small>
                                    {share.role === "viewer"
                                      ? "View only"
                                      : "View and record care"}
                                  </small>
                                </div>
                                <span
                                  className={`small-badge ${share.status === "active" ? "green" : "amber"}`}
                                >
                                  {share.status === "active"
                                    ? "Active"
                                    : "Invited"}
                                </span>
                              </div>
                              <CareAlertEditor
                                patientId={patientId}
                                grant={share}
                                onSaved={setWorkspace}
                              />
                              <button
                                className="member-revoke"
                                disabled={busy}
                                aria-label={`Revoke access for ${share.username}`}
                                onClick={() =>
                                  run(async () => {
                                    setWorkspace(
                                      await api<Workspace>(
                                        `/care/patients/${patientId}/invitations/${share.id}/revoke`,
                                        { method: "POST" },
                                      ),
                                    );
                                    setNotice(
                                      "Access revoked. Future requests are blocked; downloaded or printed copies cannot be recalled.",
                                    );
                                  })
                                }
                              >
                                Remove access
                              </button>
                            </article>
                          ))
                        ) : (
                          <div className="panel-empty">
                            <span className="settings-row-icon">
                              <Users size={25} />
                            </span>
                            <div>
                              <strong>No caregivers yet</strong>
                              <p>
                                Invite someone you trust to view records or help
                                track care.
                              </p>
                            </div>
                          </div>
                        )}
                        <button
                          className="primary wide"
                          disabled={busy}
                          onClick={() => {
                            keyboard.hide();
                            setInviteUsername("");
                            setInviteRole("viewer");
                            setSheet("sharing");
                          }}
                        >
                          <Plus size={17} />
                          Invite a caregiver
                        </button>
                        <button
                          className="settings-row family-history"
                          disabled={busy}
                          onClick={openAccessHistory}
                        >
                          <span className="settings-row-icon">
                            <CalendarBlank size={19} />
                          </span>
                          <span className="settings-row-copy">
                            <strong>Access & activity history</strong>
                            <small>
                              Invitations, permission changes and care activity
                            </small>
                          </span>
                          <CaretRight size={16} />
                        </button>
                      </>
                    ) : (
                      <div className="panel-notice">
                        <ShieldCheck size={22} />
                        <div>
                          <strong>
                            {canRecord ? "View and record care" : "View only"}
                          </strong>
                          <p>
                            {patient.owner_username} manages these records.
                            Report review, uploads and sharing stay with the
                            owner.
                          </p>
                        </div>
                      </div>
                    )}
                  </section>
                )}
                <section className="family-section">
                  <SectionHeading
                    title="Contacts"
                    action={
                      isOwner
                        ? "Add contact"
                        : !patient
                          ? "Choose profile"
                          : undefined
                    }
                    onClick={() => openCare(patient ? "contact" : null)}
                  />
                  {contactFields.map(({ report: item, field }) => (
                    <article
                      className="plain-card family-contact"
                      key={field.id}
                    >
                      <div className="person-heading">
                        <span className="settings-row-icon">
                          <FirstAidKit size={21} />
                        </span>
                        <div>
                          <h3>{field.label}</h3>
                          <small>
                            {field.origin === "manual"
                              ? "Added by you"
                              : `From ${item.name}`}
                          </small>
                        </div>
                      </div>
                      {field.status === "confirmed" ? (
                        <a
                          className="contact-call"
                          href={`tel:${field.value.replace(/[^+0-9]/g, "")}`}
                        >
                          <Phone size={18} />
                          <span>{field.value}</span>
                          <span className="contact-call-label">Call</span>
                        </a>
                      ) : (
                        <div className="contact-unconfirmed">
                          <strong>{field.value}</strong>
                          <p>
                            Check this number in the overview before calling.
                          </p>
                        </div>
                      )}
                      <button
                        className="contact-source"
                        onClick={() => {
                          acceptReport(item);
                          navigate("Review");
                        }}
                      >
                        Check source / edit label
                        <CaretRight size={15} />
                      </button>
                    </article>
                  ))}
                  {patient?.contacts.map((contact) => (
                    <article
                      className="plain-card family-contact"
                      key={contact.id}
                    >
                      <div className="person-heading">
                        <span className="member-avatar">
                          {contact.name.slice(0, 1).toUpperCase()}
                        </span>
                        <div>
                          <h3>{contact.name}</h3>
                          <small>{contact.role}</small>
                        </div>
                      </div>
                      <a
                        className="contact-call"
                        href={`tel:${contact.phone.replace(/[^+0-9]/g, "")}`}
                      >
                        <Phone size={18} />
                        <span>{contact.phone}</span>
                        <span className="contact-call-label">Call</span>
                      </a>
                      {contact.note && (
                        <p className="contact-note">{contact.note}</p>
                      )}
                      {isOwner && (
                        <button
                          className="member-revoke"
                          disabled={busy}
                          onClick={() =>
                            run(async () => {
                              setWorkspace(
                                await api<Workspace>(
                                  `/care/patients/${patientId}/contacts/${contact.id}`,
                                  { method: "DELETE" },
                                ),
                              );
                            })
                          }
                        >
                          Remove contact
                        </button>
                      )}
                    </article>
                  ))}
                  {!patient?.contacts.length && !contactFields.length && (
                    <div className="panel-empty">
                      <span className="settings-row-icon">
                        <Phone size={23} />
                      </span>
                      <div>
                        <strong>No contacts saved</strong>
                        <p>
                          {isOwner
                            ? "Add a family member or your care team's phone number."
                            : "Contacts added by the owner appear here."}
                        </p>
                      </div>
                    </div>
                  )}
                  <div className="panel-hint">
                    <Info size={16} />
                    <p>
                      Saving a contact does not grant access to your records.
                    </p>
                  </div>
                </section>
                <CareUpdates onOpen={openSharedReport} />
                <details className="panel-details">
                  <summary>How care sharing works</summary>
                  <p>
                    Invitations stay inside this installation; no email or
                    message is sent. The caregiver needs an existing account and
                    must accept before accessing records. You can remove access
                    at any time; downloaded or printed copies cannot be
                    recalled.
                  </p>
                </details>
                {report?.plan_saved && (
                  <button
                    className="settings-row family-history"
                    onClick={() => navigate("Plan")}
                  >
                    <span className="settings-row-icon">
                      <Printer size={20} />
                    </span>
                    <span className="settings-row-copy">
                      <strong>Printable care plan</strong>
                      <small>Your reviewed instructions</small>
                    </span>
                    <CaretRight size={16} />
                  </button>
                )}
              </div>
            )}
            {screen === "Review" &&
              (report ? (
                <PlanOverview
                  key={report.id}
                  report={report}
                  isOwner={!!isOwner}
                  onSaved={(next) => {
                    acceptReport(next);
                    setNotice(
                      "Overview confirmed. Choose reminder times for medicines with complete instructions.",
                    );
                    navigate("Meds");
                  }}
                />
              ) : (
                <div className="empty-inline">
                  <p>Add a prescription first.</p>
                  <button className="primary" onClick={openUpload}>
                    Add prescription
                  </button>
                </div>
              ))}
            {screen === "Plan" && report && (
              <>
                <span className="pill-label">
                  <CheckCircle size={16} weight="fill" />
                  Reviewed & saved
                </span>
                <h1>Your reviewed instructions.</h1>
                <p className="intro">
                  An organized transcription of the original document. Check the
                  original for details extraction may have missed.
                </p>
                {[
                  ...new Set(
                    report.fields
                      .filter((f) => f.status === "confirmed")
                      .map((f) => f.group),
                  ),
                ].map((group) => (
                  <section className="plan-group" key={group}>
                    <h2>{group}</h2>
                    {report.fields
                      .filter(
                        (f) => f.group === group && f.status === "confirmed",
                      )
                      .map((f) => (
                        <div key={f.id}>
                          <span>{f.label}</span>
                          <strong>{f.value}</strong>
                        </div>
                      ))}
                  </section>
                ))}
                {report.fields.some((f) => f.status === "clarify") && (
                  <div className="note">
                    <WarningCircle size={22} />
                    <p>
                      {
                        report.fields.filter((f) => f.status === "clarify")
                          .length
                      }{" "}
                      fields need clinical clarification. They are listed
                      separately in the printable plan.
                    </p>
                  </div>
                )}
                <a
                  className="primary wide"
                  href={`/api/reports/${report.id}/plan`}
                  target="_blank"
                  rel="noreferrer"
                >
                  <Printer size={20} />
                  <span>Open printable plan</span>
                  <ArrowRight size={18} />
                </a>
                <a
                  className="secondary wide"
                  href={`/api/reports/${report.id}/file`}
                >
                  <DownloadSimple size={18} />
                  Download original report
                </a>
                <p className="fine-print">
                  Saving this transcription does not activate reminders.
                  Approved schedules are managed separately in Meds.
                </p>
              </>
            )}
            <p className="prototype-label">AfterCare · V2</p>
          </main>
        </MobileScroll>
        <nav
          className="bottom-nav"
          style={{ bottom: bottomInset + 12 }}
          aria-label="Main navigation"
        >
          {tabs.map(({ name: tab, icon: Icon }) => (
            <button
              key={tab}
              className={
                screen === tab ||
                (["Review", "Plan"].includes(screen) && tab === "Reports")
                  ? "active"
                  : ""
              }
              onClick={() => navigate(tab)}
              onPointerDown={(event) => event.preventDefault()}
              disabled={busy}
              aria-current={screen === tab ? "page" : undefined}
            >
              <Icon size={21} weight={screen === tab ? "fill" : "regular"} />
              <span>{tab}</span>
            </button>
          ))}
        </nav>
        <input
          ref={input}
          type="file"
          accept=".pdf,.png,.jpg,.jpeg"
          hidden
          onChange={upload}
        />
        <BottomSheet
          open={sheet !== null}
          onOpenChange={(open) => !open && setSheet(null)}
          title={
            sheet === "manual-visit"
              ? "Add a visit"
              : sheet === "manual-medicine"
                ? "Add a medicine"
                : sheet === "routine"
                  ? "Your daily routine"
                  : sheet === "delete-report"
                    ? "Delete report"
                    : sheet === "security"
                      ? "Account security"
                      : sheet === "record-medication"
                        ? "Record a medicine"
                        : sheet === "account"
                          ? "Account settings"
                          : sheet === "legacy-import"
                            ? "Previous local reports"
                            : sheet === "questions"
                              ? "Questions for your care team"
                              : sheet === "report-options"
                                ? "Your report"
                                : sheet === "archives"
                                  ? "Archived reports"
                                  : sheet === "sharing"
                                    ? "Invite a caregiver"
                                    : sheet === "access-history"
                                      ? "Access and activity history"
                                      : sheet === "care"
                                        ? careMode === "contact"
                                          ? "Add contact"
                                          : careMode === "patient"
                                            ? "Add patient"
                                            : careMode === "episode"
                                              ? "Add recovery"
                                              : "Existing records"
                                        : sheet === "upload"
                                          ? "Add to your medicines"
                                          : sheet === "about"
                                            ? "About AfterCare"
                                            : sheet === "history"
                                              ? "Your review history"
                                              : sheet === "medication"
                                                ? selectedMedication?.name ||
                                                  "Medication details"
                                                : sheet === "visit"
                                                  ? "Your next step"
                                                  : "Reminders & updates"
          }
          description={
            sheet === "upload"
              ? "Upload a prescription or enter a medicine yourself."
              : undefined
          }
        >
          <button
            className="sheet-close"
            aria-label="Close dialog"
            onClick={() => {
              keyboard.hide();
              setSheet(null);
            }}
          >
            <X size={18} />
          </button>
          {error && (
            <div className="sheet-body">
              <div className="error-banner" role="alert">
                <WarningCircle size={20} />
                <span>{error}</span>
              </div>
            </div>
          )}
          {sheet === "report-options" && isOwner && managedReport && (
            <div className="sheet-body report-management">
              <div className="report-identity">
                <FileText size={26} />
                <strong>{managedReport.name}</strong>
              </div>
              {confirmArchive ? (
                <>
                  <h3>Archive this report?</h3>
                  <p>
                    It will disappear from active reports for you and your
                    caregivers. The report and its care records stay saved.
                  </p>
                  <p>
                    You can restore it later. Restoring also makes it available
                    to caregivers who still have access. Downloaded copies
                    cannot be recalled.
                  </p>
                  <button
                    className="primary wide"
                    disabled={busy}
                    onClick={archiveReport}
                  >
                    <Archive size={18} /> Archive this report
                  </button>
                  <button
                    className="secondary wide"
                    disabled={busy}
                    onClick={() => setConfirmArchive(false)}
                  >
                    Keep report active
                  </button>
                </>
              ) : (
                <>
                  <div className="settings-list report-actions">
                    <button
                      className="settings-row"
                      disabled={busy}
                      onClick={() =>
                        run(async () => {
                          await downloadReport(managedReport.id);
                          setSheet(null);
                          setNotice(
                            "Report copy prepared. Check your browser downloads.",
                          );
                        })
                      }
                    >
                      <span className="settings-row-icon">
                        <DownloadSimple size={20} />
                      </span>
                      <span className="settings-row-copy">
                        <strong>Download report copy</strong>
                        <small>
                          {managedReport.kind === "manual"
                            ? "Entered details, reviews and care records"
                            : "Original, source evidence, reviews and care records"}
                        </small>
                      </span>
                      <CaretRight size={16} />
                    </button>
                    <button
                      className="settings-row"
                      disabled={busy}
                      onClick={() => openHistory(managedReport.id)}
                    >
                      <span className="settings-row-icon">
                        <CalendarBlank size={20} />
                      </span>
                      <span className="settings-row-copy">
                        <strong>Review history</strong>
                        <small>Corrections and saved decisions</small>
                      </span>
                      <CaretRight size={16} />
                    </button>
                    <button
                      className="settings-row"
                      disabled={busy}
                      onClick={() => setConfirmArchive(true)}
                    >
                      <span className="settings-row-icon">
                        <Archive size={20} />
                      </span>
                      <span className="settings-row-copy">
                        <strong>Archive report</strong>
                        <small>Keep it saved and restore it later</small>
                      </span>
                      <CaretRight size={16} />
                    </button>
                    <button
                      className="settings-row destructive-row"
                      disabled={busy}
                      onClick={() => {
                        keyboard.hide();
                        setSheet("delete-report");
                      }}
                    >
                      <span className="settings-row-icon">
                        <X size={20} />
                      </span>
                      <span className="settings-row-copy">
                        <strong>Delete report…</strong>
                        <small>
                          Permanently remove this report and its care records
                        </small>
                      </span>
                      <CaretRight size={16} />
                    </button>
                  </div>
                  <div className="panel-hint">
                    <Info size={17} />
                    <p>
                      Downloaded ZIP copies are unencrypted and cannot be
                      imported into the app.
                    </p>
                  </div>
                </>
              )}
            </div>
          )}
          {sheet === "archives" && isOwner && (
            <div className="sheet-body report-management">
              <p>
                Saved for later in {episode?.title}. Caregivers cannot open
                archived reports.
              </p>
              {archives
                .filter((item) => item.episode_id === episodeId)
                .map((item) => (
                  <div className="archived-report" key={item.id}>
                    <strong>{item.name}</strong>
                    <span>
                      Archived{" "}
                      {new Date(item.archived_at).toLocaleDateString("en-IN")}
                    </span>
                    <button
                      className="secondary wide"
                      disabled={busy}
                      onClick={() => restoreReport(item)}
                    >
                      Restore report
                    </button>
                    <button
                      className="text-button"
                      disabled={busy}
                      onClick={() => {
                        setDeleting(item);
                        setDeleteName("");
                        setDeletePassword("");
                      }}
                    >
                      Permanently delete…
                    </button>
                  </div>
                ))}
              {deleting && (
                <form
                  className="stop-confirm account-form"
                  onSubmit={(e) => {
                    e.preventDefault();
                    keyboard.hide();
                    void run(async () => {
                      await api(
                        `/reports/${deleting.id}`,
                        jsonRequest("DELETE", {
                          current_password: deletePassword,
                          name: deleteName,
                        }),
                      );
                      setArchives(
                        await api<ArchivedReport[]>("/reports/archived"),
                      );
                      setDeleting(null);
                      setDeleteName("");
                      setDeletePassword("");
                      setNotice(
                        "Report, original and related records permanently deleted from this installation.",
                      );
                    });
                  }}
                >
                  <h3>Delete this report permanently?</h3>
                  <p>
                    This removes its original document, review history,
                    schedules and care records from this installation. Backups
                    and downloaded or printed copies remain. This cannot be
                    undone.
                  </p>
                  <label className="activity-label">
                    Type the exact name: {deleting.name}
                    <KeyboardInput
                      aria-label="Report name for permanent deletion"
                      value={deleteName}
                      onChange={(e) => setDeleteName(e.target.value)}
                      onBlur={() => keyboard.hide()}
                      required
                    />
                  </label>
                  <label className="activity-label">
                    Current password
                    <KeyboardInput
                      aria-label="Password for permanent deletion"
                      type="password"
                      autoComplete="current-password"
                      value={deletePassword}
                      onChange={(e) => setDeletePassword(e.target.value)}
                      onBlur={() => keyboard.hide()}
                      required
                    />
                  </label>
                  {error && (
                    <p role="alert" className="error">
                      {error}
                    </p>
                  )}
                  <button
                    className="primary wide"
                    type="submit"
                    disabled={
                      busy || deleteName !== deleting.name || !deletePassword
                    }
                  >
                    Permanently delete report
                  </button>
                  <button
                    type="button"
                    className="text-button"
                    onClick={() => {
                      keyboard.hide();
                      setDeleting(null);
                      setDeletePassword("");
                      setDeleteName("");
                    }}
                  >
                    Cancel deletion
                  </button>
                </form>
              )}
              {!archives.some((item) => item.episode_id === episodeId) && (
                <div className="empty-inline">
                  <Archive size={28} />
                  <p>No archived reports in this recovery.</p>
                </div>
              )}
              <p className="management-note">
                Restoring preserves the report and makes it available to
                caregivers who still have access.
              </p>
            </div>
          )}
          {sheet === "sharing" && isOwner && (
            <form
              className="sheet-body account-form invite-form"
              onSubmit={inviteCaregiver}
            >
              <div className="panel-person">
                <span className="settings-row-icon">
                  <Users size={23} />
                </span>
                <div>
                  <small>Sharing care for</small>
                  <strong>{patient?.name}</strong>
                </div>
              </div>
              <fieldset className="panel-group">
                <legend>Caregiver details</legend>
                <label className="activity-label">
                  Caregiver username
                  <KeyboardInput
                    aria-label="Caregiver username"
                    value={inviteUsername}
                    onChange={(e) => setInviteUsername(e.target.value)}
                    onBlur={() => keyboard.hide()}
                    required
                    minLength={3}
                    maxLength={40}
                    pattern="[a-zA-Z0-9_-]+"
                    autoComplete="off"
                    placeholder="Their existing account username"
                  />
                </label>
                <label className="activity-label">
                  Permission
                  <CareSelect
                    label="Caregiver permission"
                    value={inviteRole}
                    onChange={(value) =>
                      setInviteRole(value as typeof inviteRole)
                    }
                    options={[
                      { value: "viewer", label: "View only" },
                      { value: "recorder", label: "View and record care" },
                    ]}
                  />
                </label>
                <div className="panel-hint">
                  <ShieldCheck size={18} />
                  <p>
                    {inviteRole === "recorder"
                      ? "Can record taken/skipped events, undo their own entries and update follow-up bookings/completion."
                      : "Can read and download records, without changing them."}{" "}
                    Only you can edit or review reports, upload documents,
                    manage contacts and invite others.
                  </p>
                </div>
              </fieldset>
              <AlertChoices value={inviteAlerts} onChange={setInviteAlerts} />
              <section className="sharing-scope">
                <h3>What you're sharing</h3>
                <p>
                  All current and future documents, reviewed plans, contacts and
                  activity for <strong>{patient?.name}</strong>.
                </p>
                <ul className="permission-list">
                  <li>
                    They must accept within 7 days. No email or message is sent.
                  </li>
                  <li>
                    Accepted access continues until you revoke it. Revocation
                    cannot recall printed or downloaded copies.
                  </li>
                </ul>
              </section>
              <button
                className="primary wide"
                type="submit"
                disabled={busy || !inviteUsername.trim()}
                onPointerDown={(e) => e.preventDefault()}
              >
                Send invitation
                <ArrowRight size={18} />
              </button>
            </form>
          )}
          {sheet === "access-history" && (
            <div className="sheet-body history-list panel-history">
              {accessHistory.length ? (
                accessHistory.map((event) => (
                  <div className="history-row" key={event.id}>
                    <strong>
                      {event.actor_name} · {event.action.replaceAll("_", " ")}
                    </strong>
                    <p>{accessEventDetail(event)}</p>
                    <small>
                      {new Date(event.created_at).toLocaleString("en-IN")}
                    </small>
                  </div>
                ))
              ) : (
                <div className="panel-empty">
                  <span className="settings-row-icon">
                    <CalendarBlank size={23} />
                  </span>
                  <div>
                    <strong>No access activity yet</strong>
                    <p>
                      Invitations, access changes and care activity will appear
                      here.
                    </p>
                  </div>
                </div>
              )}
            </div>
          )}
          {sheet === "routine" && <RoutineSettings />}
          {sheet === "delete-report" && managedReport && (
            <div className="sheet-body">
              <DeleteReportForm
                item={managedReport}
                onDeleted={async () => {
                  await refreshWorkspace();
                  setManagedReport(null);
                  setSheet(null);
                  setNotice("Report and its reminders deleted.");
                }}
              />
            </div>
          )}
          {sheet === "account" && (
            <div className="sheet-body account-settings">
              <div className="settings-profile">
                <span className="settings-avatar" aria-hidden="true">
                  {account.username.slice(0, 1).toUpperCase()}
                </span>
                <div>
                  <strong>{account.username}</strong>
                  <span>Your AfterCare account</span>
                </div>
              </div>
              <div className="settings-list">
                {[
                  {
                    label: "Daily routine",
                    detail: "Wake, meals and sleep",
                    icon: Stethoscope,
                    action: () => {
                      keyboard.hide();
                      setSheet("routine");
                    },
                  },
                  {
                    label: "Account security",
                    detail: "Password and recovery code",
                    icon: ShieldCheck,
                    action: openSecurity,
                  },
                  {
                    label: "Existing records",
                    detail: "Saved profiles and document groups",
                    icon: Users,
                    action: () => openCare(),
                  },
                  {
                    label: "About AfterCare",
                    detail: "About the app, storage and backups",
                    icon: Info,
                    action: () => {
                      keyboard.hide();
                      setSheet("about");
                    },
                  },
                ].map(({ label, detail, icon: Icon, action }) => (
                  <button
                    className="settings-row"
                    key={label}
                    disabled={busy}
                    onClick={action}
                  >
                    <span className="settings-row-icon">
                      <Icon size={21} />
                    </span>
                    <span className="settings-row-copy">
                      <strong>{label}</strong>
                      <small>{detail}</small>
                    </span>
                    <CaretRight size={17} className="settings-chevron" />
                  </button>
                ))}
              </div>
              <button
                className="settings-signout"
                disabled={busy}
                onClick={() => run(signOut)}
              >
                <SignOut size={20} />
                Sign out
              </button>
            </div>
          )}
          {sheet === "security" && (
            <form
              className="sheet-body account-form security-settings"
              onSubmit={changePassword}
            >
              <div className="panel-person">
                <span className="settings-row-icon">
                  <ShieldCheck size={23} />
                </span>
                <div>
                  <strong>Protect your account</strong>
                  <small>Password and account recovery</small>
                </div>
              </div>
              <fieldset className="panel-group">
                <legend>Verify your identity</legend>
                <label className="activity-label">
                  Current password
                  <KeyboardInput
                    aria-label="Current password"
                    type="password"
                    autoComplete="current-password"
                    value={securityPassword}
                    onChange={(e) => setSecurityPassword(e.target.value)}
                    onBlur={() => keyboard.hide()}
                    maxLength={128}
                    required
                  />
                </label>
              </fieldset>
              <section className="panel-group">
                <div className="panel-group-heading">
                  <h3>Account recovery</h3>
                  <span
                    className={`small-badge ${recoveryConfigured ? "green" : "amber"}`}
                  >
                    {recoveryConfigured ? "Configured" : "Not set up"}
                  </span>
                </div>
                <p className="panel-help">
                  A recovery code can reset your password once. Creating a new
                  code replaces the previous one.
                </p>
                {recoveryCode && (
                  <div className="recovery-code-box" role="status">
                    <strong>Save this code privately</strong>
                    <code>{recoveryCode}</code>
                    <button
                      type="button"
                      className="secondary wide"
                      onClick={async () => {
                        try {
                          await navigator.clipboard.writeText(recoveryCode);
                          setRecoveryCopyMessage(
                            "Copied. Store it privately outside the app.",
                          );
                        } catch {
                          setRecoveryCopyMessage(
                            "Copy is unavailable. Select the code and copy it manually.",
                          );
                        }
                      }}
                    >
                      Copy recovery code
                    </button>
                    {recoveryCopyMessage && (
                      <p role="status">{recoveryCopyMessage}</p>
                    )}
                    <p>
                      It is shown once. Anyone with this code and your username
                      can reset your password. It is revoked when used,
                      replaced, or your password changes.
                    </p>
                    <button
                      type="button"
                      className="secondary wide"
                      onClick={() => setRecoveryCode("")}
                    >
                      I stored it safely
                    </button>
                  </div>
                )}
                <button
                  className="secondary wide"
                  type="button"
                  disabled={busy || !securityPassword}
                  onClick={generateRecovery}
                >
                  {recoveryConfigured
                    ? "Replace recovery code"
                    : "Create recovery code"}
                </button>
              </section>
              <fieldset className="panel-group">
                <legend>Change password</legend>
                <label className="activity-label">
                  New password
                  <KeyboardInput
                    aria-label="New password"
                    type="password"
                    autoComplete="new-password"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    onBlur={() => keyboard.hide()}
                    minLength={12}
                    maxLength={128}
                    required
                  />
                </label>
                <label className="activity-label">
                  Confirm new password
                  <KeyboardInput
                    aria-label="Confirm new password"
                    type="password"
                    autoComplete="new-password"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    onBlur={() => keyboard.hide()}
                    minLength={12}
                    maxLength={128}
                    required
                  />
                </label>
                <p className="fine-print">
                  At least 12 characters. Changing your password signs out other
                  sessions and revokes your recovery code. Your records are
                  retained.
                </p>
              </fieldset>
              <button
                className="primary wide"
                disabled={
                  busy ||
                  !securityPassword ||
                  newPassword.length < 12 ||
                  newPassword !== confirmPassword
                }
                type="submit"
                onPointerDown={(e) => e.preventDefault()}
              >
                Change password
              </button>
            </form>
          )}
          {sheet === "record-medication" && (
            <div className="sheet-body">
              <p>
                Choose a medicine to record what happened. These are manual
                events, not scheduled doses.
              </p>
              {meds.map((med) => (
                <button
                  className="document-card"
                  key={med.group}
                  disabled={!canRecord || !report?.plan_saved || !med.reviewed}
                  onClick={() => openMedication(med.group)}
                >
                  <Pill size={24} />
                  <div>
                    <strong>{med.name}</strong>
                    <span>{med.strength || "Strength not stated"}</span>
                    <span>
                      {med.reviewed && report?.plan_saved
                        ? "Record taken or skipped"
                        : "Review the instructions before recording"}
                    </span>
                  </div>
                  <CaretRight size={16} />
                </button>
              ))}
              {!meds.length && (
                <p>No medicines were extracted. Check the original document.</p>
              )}
            </div>
          )}
          {sheet === "legacy-import" && isOwner && (
            <div className="sheet-body">
              {!!workspace.legacy_count && episodeId && isOwner && (
                <div className="legacy-import">
                  <h2>Previous local reports</h2>
                  <p>
                    {workspace.legacy_count} reports were created before
                    accounts. Import all of them into{" "}
                    <strong>
                      {patient?.name === "Me" ? "me" : patient?.name}
                    </strong>{" "}
                    only if they belong together. This action assigns them to
                    your account.
                  </p>
                  <button
                    className="secondary wide"
                    disabled={busy}
                    onClick={importLocal}
                  >
                    Import previous local reports
                  </button>
                </div>
              )}
            </div>
          )}
          {sheet === "questions" && report && (
            <div className="sheet-body care-questions">
              <p>
                These details were flagged as unclear. Take the original
                document and these questions to your care team. Reviewing a
                transcription does not resolve a clinical question.
              </p>
              {summary.questions.map((field) => (
                <article className="care-question" key={field.id}>
                  <span>
                    {field.group} / {field.label}
                  </span>
                  <h3>{field.value || "Information not stated"}</h3>
                  <p>Ask your care team to clarify this detail.</p>
                  <blockquote>
                    {field.source?.text ||
                      "No source excerpt captured. Check the original document."}
                  </blockquote>
                  {field.source && (
                    <small>Source page {field.source.page + 1}</small>
                  )}
                  <button
                    className="secondary wide"
                    onClick={() => openReview(field)}
                  >
                    Check source for {field.label}
                    <CaretRight size={16} />
                  </button>
                </article>
              ))}
              {!summary.questions.length && (
                <p>
                  No details are currently flagged. Extraction may still have
                  missed information; check the original document.
                </p>
              )}
              <a
                className="secondary wide"
                href={`/api/reports/${report.id}/file`}
                target="_blank"
                rel="noreferrer"
              >
                <FileText size={18} /> Open original document
              </a>
            </div>
          )}
          {sheet === "care" && (
            <div className="sheet-body care-setup">
              {!careMode && (
                <div className="panel-notice">
                  <Users size={23} />
                  <div>
                    <strong>Choose whose records to view</strong>
                    <p>
                      Profiles keep each person's records separate. Older
                      records stay in their saved document groups.
                    </p>
                  </div>
                </div>
              )}
              {!careMode && !!workspace.legacy_count && (
                <button
                  className="secondary wide"
                  disabled={busy || !isOwner || !episodeId}
                  onClick={() => {
                    keyboard.hide();
                    setSheet("legacy-import");
                  }}
                >
                  <FileText size={18} />
                  Previous local reports ({workspace.legacy_count})
                </button>
              )}
              {careMode &&
                careMode !== "contact" &&
                workspace.patients.length > 0 && (
                  <button
                    className="text-button"
                    onClick={() => {
                      keyboard.hide();
                      setCareMode(null);
                    }}
                  >
                    Back to saved profiles
                  </button>
                )}
              {workspace.patients.length > 0 && !careMode && (
                <>
                  <label className="activity-label">
                    Who is receiving care?
                    <CareSelect
                      label="Patient profile"
                      value={patientId}
                      disabled={busy}
                      onChange={(value) => {
                        const p = workspace.patients.find(
                          (p) => p.id === value,
                        )!;
                        chooseEpisode(p.id, p.episodes[0]?.id || "");
                      }}
                      options={workspace.patients.map((p) => ({
                        value: p.id,
                        label: `${p.name}${p.access_role !== "owner" ? " (shared)" : ""}`,
                      }))}
                    />
                  </label>
                  <label className="activity-label">
                    Saved document group
                    <CareSelect
                      label="Recovery episode"
                      value={episodeId}
                      disabled={busy}
                      placeholder="Choose an existing document group"
                      onChange={(value) => chooseEpisode(patientId, value)}
                      options={
                        patient?.episodes.map((e) => ({
                          value: e.id,
                          label: `${e.title} · ${e.started}`,
                        })) || []
                      }
                    />
                  </label>
                </>
              )}
              {careMode && (
                <form
                  className="account-form panel-group contact-form"
                  onSubmit={saveCare}
                >
                  {careMode === "contact" ? (
                    <div className="panel-person">
                      <span className="settings-row-icon">
                        <Phone size={21} />
                      </span>
                      <div>
                        <strong>New contact</strong>
                        <small>For {patient?.name}</small>
                      </div>
                    </div>
                  ) : (
                    <h2>
                      {careMode === "patient"
                        ? "New patient profile"
                        : `New recovery for ${patient?.name}`}
                    </h2>
                  )}
                  <label className="activity-label">
                    {careMode === "patient"
                      ? "Patient name"
                      : careMode === "episode"
                        ? "Recovery title"
                        : "Contact name"}
                    <KeyboardInput
                      aria-label={
                        careMode === "patient"
                          ? "Patient name"
                          : careMode === "episode"
                            ? "Recovery title"
                            : "Contact name"
                      }
                      value={careName}
                      onChange={(e) => setCareName(e.target.value)}
                      onBlur={() => keyboard.hide()}
                      required
                      maxLength={100}
                      placeholder={
                        careMode === "episode"
                          ? "e.g. October discharge"
                          : "Full name"
                      }
                    />
                  </label>
                  {careMode === "episode" && (
                    <label className="activity-label">
                      Start date (YYYY-MM-DD)
                      <KeyboardInput
                        aria-label="Recovery start date"
                        value={started}
                        onChange={(e) => setStarted(e.target.value)}
                        onBlur={() => keyboard.hide()}
                        placeholder="YYYY-MM-DD"
                        required
                        maxLength={10}
                        pattern="[0-9]{4}-[0-9]{2}-[0-9]{2}"
                      />
                    </label>
                  )}
                  {careMode === "contact" && (
                    <>
                      <label className="activity-label">
                        Relationship / role
                        <KeyboardInput
                          aria-label="Contact role"
                          value={contactRole}
                          onChange={(e) => setContactRole(e.target.value)}
                          onBlur={() => keyboard.hide()}
                          placeholder="e.g. Sister or care coordinator"
                          required
                          maxLength={80}
                        />
                      </label>
                      <label className="activity-label">
                        Phone number
                        <KeyboardInput
                          aria-label="Contact phone"
                          type="tel"
                          value={phone}
                          onChange={(e) => setPhone(e.target.value)}
                          onBlur={() => keyboard.hide()}
                          required
                          maxLength={30}
                        />
                      </label>
                      <label className="activity-label">
                        Note (optional)
                        <KeyboardInput
                          aria-label="Contact note"
                          value={contactNote}
                          onChange={(e) => setContactNote(e.target.value)}
                          onBlur={() => keyboard.hide()}
                          maxLength={300}
                        />
                      </label>
                    </>
                  )}
                  <button
                    className="primary wide"
                    type="submit"
                    disabled={busy || !careName.trim()}
                    onPointerDown={(e) => e.preventDefault()}
                  >
                    {careMode === "patient"
                      ? "Save patient profile"
                      : careMode === "episode"
                        ? "Create recovery episode"
                        : "Save contact"}
                    <Check size={18} />
                  </button>
                </form>
              )}
              {episodeId && !careMode && (
                <button className="primary wide" onClick={() => setSheet(null)}>
                  View this recovery
                  <ArrowRight size={18} />
                </button>
              )}
              {!careMode && (
                <button
                  className="settings-row family-history"
                  onClick={() => {
                    keyboard.hide();
                    setSheet("account");
                  }}
                >
                  <span className="settings-row-icon">
                    <UserCircle size={21} />
                  </span>
                  <span className="settings-row-copy">
                    <strong>Account settings</strong>
                  </span>
                  <CaretRight size={16} />
                </button>
              )}
            </div>
          )}
          {sheet === "medication" && selectedMedication && (
            <div className="sheet-body">
              <div className="medication-facts">
                {selectedMedication.fields.map((field) => (
                  <div key={field.id}>
                    <span>{field.label}</span>
                    <strong>{field.value}</strong>
                  </div>
                ))}
              </div>
              <button
                className="text-button"
                onClick={() => {
                  setSheet(null);
                  select(selectedMedication.fields[0]);
                  navigate("Review");
                }}
              >
                {report?.kind === "manual"
                  ? "Edit medicine details"
                  : "Check the original instructions"}{" "}
                <ArrowRight size={14} />
              </button>
              {!canRecord ? (
                <div className="note">
                  <Info size={19} />
                  <p>
                    Your access is view only. Ask the owner if you need
                    permission to record care.
                  </p>
                </div>
              ) : !report?.plan_saved || !selectedMedication.reviewed ? (
                <div className="note">
                  <Info size={19} />
                  <p>
                    {isOwner
                      ? "Confirm the prescription overview before recording activity."
                      : "The owner must review the medication details and save the plan before care can be recorded."}
                  </p>
                </div>
              ) : (
                <>
                  <p className="log-explanation">
                    Record what happened. Follow your prescribed instructions;
                    no dose or schedule is suggested here.
                  </p>
                  <label className="activity-label">
                    Note (optional)
                    <KeyboardInput
                      aria-label="Medication note"
                      value={activityNote}
                      onChange={(e) => setActivityNote(e.target.value)}
                      onBlur={() => keyboard.hide()}
                      maxLength={500}
                      placeholder="Add a note to this record"
                    />
                  </label>
                  <div className="log-actions">
                    <button
                      className="secondary"
                      disabled={busy}
                      onClick={() => logMedication("skipped")}
                      onPointerDown={(event) => event.preventDefault()}
                    >
                      <X size={17} />
                      Record skipped
                    </button>
                    <button
                      className="primary"
                      disabled={busy}
                      onClick={() => logMedication("taken")}
                      onPointerDown={(event) => event.preventDefault()}
                    >
                      <Check size={17} />
                      Record taken
                    </button>
                  </div>
                  <p className="fine-print">
                    Records use the current time. You can undo an accidental
                    entry.
                  </p>
                </>
              )}
              {report && (
                <MedicineExplanation
                  reportId={report.id}
                  group={medicationGroup}
                />
              )}
              <SectionHeading title="Recent records" />
              {recentActivity(medicationGroup)}
            </div>
          )}
          {sheet === "visit" && visitField && (
            <div className="sheet-body">
              <div className="visit-instruction">
                <span>{visitField.label}</span>
                <p>{visitField.value}</p>
                <button
                  className="text-button"
                  onClick={() => {
                    setSheet(null);
                    select(visitField);
                    navigate("Review");
                  }}
                >
                  {visitField.origin === "manual"
                    ? "Edit visit details"
                    : "View source"}{" "}
                  <ArrowRight size={14} />
                </button>
              </div>
              {!canRecord &&
                activity.visits
                  .filter((v) => v.field_id === visitField.id)
                  .map((v) => (
                    <div className="visit-instruction" key={v.field_id}>
                      <strong>
                        {v.status === "booked"
                          ? `Booked for ${v.planned_date}`
                          : v.status === "completed"
                            ? "Completed"
                            : "Not booked"}
                      </strong>
                      {v.note && <p>{v.note}</p>}
                      <span className="record-author">
                        Last updated by{" "}
                        {v.actor_name || "earlier record (author unavailable)"}
                      </span>
                    </div>
                  ))}
              {!canRecord ? (
                <div className="note">
                  <Info size={19} />
                  <p>
                    Your access is view only. You can inspect the booking and
                    original instruction.
                  </p>
                </div>
              ) : !report?.plan_saved || visitField.status !== "confirmed" ? (
                <div className="note">
                  <Info size={19} />
                  <p>
                    {isOwner
                      ? "Review this instruction and save the care plan before tracking it."
                      : "The owner must review this instruction and save the plan before care can be recorded."}
                  </p>
                </div>
              ) : (
                <>
                  <p className="log-explanation">
                    Enter the date you actually booked. This does not change
                    your discharge instructions.
                  </p>
                  <fieldset className="booking-date">
                    <legend>Booked for</legend>
                    <CareSelect
                      label="Appointment day"
                      value={bookingDate.day}
                      placeholder="Day"
                      onChange={(value) => changeBookingDate("day", value)}
                      options={Array.from(
                        {
                          length: new Date(
                            Number(bookingDate.year) ||
                              new Date().getFullYear(),
                            Number(bookingDate.month) || 1,
                            0,
                          ).getDate(),
                        },
                        (_, index) => ({
                          value: String(index + 1).padStart(2, "0"),
                          label: String(index + 1),
                        }),
                      )}
                    />
                    <CareSelect
                      label="Appointment month"
                      value={bookingDate.month}
                      placeholder="Month"
                      onChange={(value) => changeBookingDate("month", value)}
                      options={Array.from({ length: 12 }, (_, index) => ({
                        value: String(index + 1).padStart(2, "0"),
                        label: new Date(2000, index, 1).toLocaleDateString(
                          "en-IN",
                          { month: "short" },
                        ),
                      }))}
                    />
                    <CareSelect
                      label="Appointment year"
                      value={bookingDate.year}
                      placeholder="Year"
                      onChange={(value) => changeBookingDate("year", value)}
                      options={Array.from({ length: 21 }, (_, index) => {
                        const year = new Date().getFullYear() - 10 + index;
                        return { value: String(year), label: String(year) };
                      })}
                    />
                  </fieldset>
                  <label className="activity-label">
                    Note (optional)
                    <KeyboardInput
                      aria-label="Appointment note"
                      value={activityNote}
                      onChange={(e) => setActivityNote(e.target.value)}
                      onBlur={() => keyboard.hide()}
                      maxLength={500}
                      placeholder="Location, time or a question to ask"
                    />
                  </label>
                  <button
                    className="primary wide"
                    disabled={busy || !visitDate}
                    onClick={() => saveVisit("booked")}
                    onPointerDown={(event) => event.preventDefault()}
                  >
                    <CalendarBlank size={19} />
                    Save booking
                  </button>
                  <button
                    className="secondary wide"
                    disabled={busy}
                    onClick={() => saveVisit("completed")}
                    onPointerDown={(event) => event.preventDefault()}
                  >
                    <CheckCircle size={19} />
                    Mark completed
                  </button>
                  {activity.visits.some(
                    (v) => v.field_id === visitField.id,
                  ) && (
                    <button
                      className="text-button clear-booking"
                      disabled={busy}
                      onClick={() => saveVisit("planned")}
                    >
                      Clear booking / completion
                    </button>
                  )}
                </>
              )}
            </div>
          )}
          {sheet === "upload" && (
            <div className="sheet-body">
              <p className="upload-context">
                Medicines for <strong>{patient?.name}</strong>. Choose how you
                want to add them.
              </p>
              <div className="note">
                <ShieldCheck size={20} />
                <p>
                  Reading happens on this installation. Check the extracted
                  details against the original before setting reminders.
                </p>
              </div>
              <button
                className="primary wide"
                disabled={busy}
                onClick={() => input.current?.click()}
              >
                <UploadSimple size={20} />
                Upload prescription or report
              </button>
              <button
                className="secondary wide"
                disabled={busy}
                onClick={() => {
                  keyboard.hide();
                  setSheet("manual-medicine");
                }}
              >
                <Pill size={20} />
                Add medicine manually
              </button>
              <button
                className="secondary wide"
                disabled={busy}
                onClick={() => loadSample()}
              >
                <Sparkle size={19} />
                Explore a fictional report
              </button>
              <button
                className="text-button scan-sample"
                disabled={busy || !ocrAvailable}
                onClick={() => loadSample("scan")}
              >
                <FileText size={16} />
                Try a scanned sample
              </button>
              <p className="fine-print">
                PDF, JPG or PNG · 12 MB · Up to 12 pages
                <br />
                {ocrAvailable
                  ? "Local OCR is ready for photos and scanned PDFs."
                  : "Photos and scanned PDFs require local Tesseract OCR."}
              </p>
            </div>
          )}
          {sheet === "manual-visit" && isOwner && (
            <ManualVisitForm
              episodeId={episodeId}
              onSaved={(next) => {
                setReports((items) => [
                  next,
                  ...items.filter((r) => r.id !== next.id),
                ]);
                setSheet(null);
                window.dispatchEvent(new Event("aftercare-visits-updated"));
                setNotice(
                  "Visit saved. Your prescription instructions stay unchanged.",
                );
              }}
            />
          )}
          {sheet === "manual-medicine" && isOwner && (
            <ManualMedicineForm
              episodeId={episodeId}
              onSaved={(next) => {
                acceptReport(next);
                if (
                  !next.fields.some(
                    (field) =>
                      field.label === "Frequency" &&
                      /as needed/i.test(field.value),
                  )
                )
                  setNewManualReminder(next.id);
                setSheet(null);
                navigate("Meds");
              }}
            />
          )}
          {sheet === "about" && (
            <div className="sheet-body about-settings">
              <div className="about-identity">
                <FirstAidKit size={32} weight="duotone" />
                <div>
                  <strong>AfterCare</strong>
                  <span>Personal medicine and care organizer</span>
                </div>
              </div>
              <p>
                Keep prescriptions, manually added medicines, reminders and care
                records together. Check extracted details once and choose your
                personal reminder times.
              </p>
              <section>
                <h3>Your records</h3>
                <p>
                  Documents are processed and stored by this AfterCare
                  installation. Records are encrypted at rest. Caretakers can
                  access shared records only after accepting an invitation; you
                  control their permissions.
                </p>
              </section>
              <section>
                <h3>Exports and backups</h3>
                <p>
                  Downloaded ZIP exports are unencrypted copies of individual
                  records, not restorable account backups. Encrypted
                  installation backup and restore are available offline to the
                  installation administrator.
                </p>
              </section>
              <section>
                <h3>Reminders and medicine information</h3>
                <p>
                  Reminders start after you confirm the details and times.
                  Browser notifications need permission and a running server.
                  Medicine information explains documented details and general
                  uses; AfterCare does not diagnose, prescribe or clinically
                  validate a treatment.
                </p>
              </section>
            </div>
          )}
          {sheet === "updates" && (
            <div className="sheet-body notifications-panel">
              <ReminderControls accountId={account.id} />
              <CareUpdates onOpen={openSharedReport} />
              {!!(
                workspace.invitations.length ||
                pending ||
                summary.questions.length
              ) && <SectionHeading title="Needs your attention" />}
              {!!workspace.invitations.length && (
                <button
                  className="secondary wide"
                  onClick={() => {
                    setSheet(null);
                    navigate("Family");
                  }}
                >
                  View care circle invitations
                  <Users size={18} />
                </button>
              )}
              {!!pending && (
                <button
                  className="primary wide"
                  onClick={() => {
                    setSheet(null);
                    navigate("Review");
                  }}
                >
                  Review your report <ArrowRight />
                </button>
              )}
              {!!summary.questions.length && (
                <button
                  className="secondary wide"
                  onClick={() => setSheet("questions")}
                >
                  Open care questions
                </button>
              )}
            </div>
          )}
          {sheet === "history" && (
            <div className="sheet-body history-list panel-history">
              {history.length ? (
                history.map((item) => {
                  const after = JSON.parse(item.after) as CareField;
                  return (
                    <div key={item.id}>
                      <strong>
                        {after.group} · {after.label}
                      </strong>
                      <p>{after.value}</p>
                      <span>
                        {statusText[after.status]} ·{" "}
                        {new Date(item.created).toLocaleString("en-IN")}
                      </span>
                    </div>
                  );
                })
              ) : (
                <div className="panel-empty">
                  <span className="settings-row-icon">
                    <FileText size={23} />
                  </span>
                  <div>
                    <strong>No reviews yet</strong>
                    <p>Corrections and review decisions will appear here.</p>
                  </div>
                </div>
              )}
            </div>
          )}
        </BottomSheet>
      </div>
    </MotionConfig>
  );
}
