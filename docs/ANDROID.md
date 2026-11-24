# Android test app

AfterCare's Android client packages the existing React interface with Capacitor. It uses the phone's keyboard and system bars, while the desktop web preview keeps its simulated devices. The initial test build connects to the Python API on your computer over USB; it does not expose the API to the internet.

## Build on Windows

Install the Python and Node dependencies from the root README first. Android command-line tools, Microsoft OpenJDK 21 and Gradle are installed under `.tools`, which is ignored by Git. Archive checksums are verified against the publishers' SHA-256 values. The setup flag below explicitly authorizes accepting Google's SDK license for the required packages.

```powershell
.venv/Scripts/python.exe scripts/setup_android.py --accept-sdk-license
.venv/Scripts/python.exe scripts/build_android.py
```

The build produces `releases/AfterCare-2.1.0-test.apk`, signed with a development key. This is a test build, not a Play Store release. Generated APKs, local SDKs, build caches and signing keys are excluded from source control. The Android app requires Android 7 or newer and a supported Android System WebView.

## Install and connect

Start the updated API on your computer:

```powershell
.venv/Scripts/python.exe scripts/run.py
```

On your Android phone, enable Developer options and USB debugging. Connect it by USB and approve this computer when Android asks. In a second terminal, from the project root:

```powershell
.venv/Scripts/python.exe scripts/connect_android.py
```

The script installs the APK, forwards the phone's `localhost:8000` to the computer's port 8000 using `adb reverse`, and opens AfterCare. With multiple devices, pass `--serial DEVICE_ID`. USB debugging approval must be done by the phone owner.

Sign in using an account on this installation. Review a prescription or enter medicines manually, then explicitly confirm reminder dates and times. The phone downloads a snapshot automatically; check the **Saved on this phone** status before disconnecting. Open the bell and enable **Phone reminders**. Android notification permission and, for precise timing, the Alarms & reminders setting must be granted by the user.

Keep the computer server running and the USB link connected for imports, account operations, new plans and synchronization. The Android app itself stays installed after disconnecting. Downloaded owner plans and dose recording remain available offline within their downloaded period. Reconnect the cable and rerun the connection script if the ADB forwarding was lost after a reboot or cable change.

## Offline behavior

- The phone saves owners' report details, activity and confirmed schedule occurrences in an AES-GCM encrypted file. Its key stays in Android Keystore; backups of the app's private data are disabled. No patient record is stored in browser localStorage.
- Occurrences are calculated by the existing backend with the confirmed time zone and timing constraints. The client does not infer frequency, regenerate instructions or call AI to send a reminder.
- A snapshot covers up to seven days. Future local notifications stop at its expiry, or earlier at course end. Open the app while connected to refresh the window. At most the next 256 notifications are scheduled; Android can delay delivery or suppress it when permissions or device settings prevent it.
- Taken, Skipped, Snooze and Undo save to an encrypted outbox before being shown locally. The status panel distinguishes pending sync from server records. Caretakers receive recorded updates only after synchronization.
- Requests include a stable ID, source fingerprint and previous record version. Retries are idempotent. A changed plan, stopped reminder or dose edited on another device causes a visible conflict instead of an overwrite. **Keep server version** retains the rejected entry in the phone's local review history and removes it from the retry queue.
- Plan-affecting writes pause local alerts before the request is sent. A failed or ambiguous connection requires a fresh server snapshot before alerts and new dose recordings resume. Changes made on another device cannot reach a disconnected phone until synchronization.
- Shared caretaker records are not downloaded for offline use. The test client refreshes caretaker activity while open and connected. Native background caretaker push is not configured in this version; the existing browser Web Push implementation remains available in the web app.
- Source images and original files are retrieved on demand while connected. Opening an original or export creates a temporary file in Android's private cache and grants the chosen viewer access. These temporary copies are outside the encrypted plan vault. As with downloaded exports, copies retained by another application cannot be recalled.

Sign-out clears downloaded plans and scheduled phone alerts. Pending or conflicted dose recordings must be synchronized or reviewed first so sign-out cannot silently discard them. A server-rejected session locks offline access and pauses notifications until sign-in. Uninstalling the app removes its local data, including any unsynchronized recordings.

## Test before using real records

Use fictional records for the first device checks:

1. Install, sign in, add/review a medicine, confirm its plan and enable reminders.
2. Check that **Saved on this phone** shows a successful sync. Disconnect USB and enable airplane mode.
3. Reopen AfterCare, view the plan, record a due dose and restart the app. Verify that the recording remains marked as waiting to sync.
4. Lock the phone and verify a user-confirmed future reminder. Test notification denial, Alarms & reminders permission, phone reboot and Android battery settings.
5. Reconnect USB, run the connection script and sync. Confirm the dose appears once in server history and in an accepted caretaker account.
6. Change a dose on the server before syncing an offline recording of that same dose. Check that the conflict is shown and the server version is preserved.
7. Edit or stop a plan and verify that old alerts are cancelled. Check seven-day expiry, sign-out cleanup and account switching.

Automated tests cover snapshot permissions, schedule revisions, replay handling, concurrent recordings, local state transitions and the native layout. APK compilation and browser tests do not establish real-device alarm delivery. Physical-phone testing is still required.

## Later deployment

For use without a computer/USB connection, host the existing API over HTTPS with persistent encrypted storage, then build with its public origin:

```powershell
.venv/Scripts/python.exe scripts/build_android.py --server https://YOUR_DOMAIN
```

The API must be configured with that same public origin and secure cookies. Sync all pending recordings and sign out before replacing a test build with one configured for a different server; the vault refuses to mix records between origins. Plain HTTP is permitted only for localhost/127.0.0.1 testing; no cleartext LAN or public endpoints are enabled. Public deployment needs target-host verification. Groq is not integrated; the current extraction pipeline remains on the API host with optional local Phi. An iPhone build, release signing/store distribution and native background caretaker push require additional platform work.
