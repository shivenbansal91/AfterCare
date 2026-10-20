# AfterCare visual and interaction review

final result: passed

## First milestone evidence

- Source visual truth: `D:/AfterCare/docs/ui-reference.png` (1024 × 768).
- Implementation: `D:/AfterCare/docs/home.png` (393 × 852), `D:/AfterCare/docs/pixel-meds.png` (427 × 952), `D:/AfterCare/docs/review.png` (393 × 852).
- Full-view comparison: `D:/AfterCare/docs/design-comparison.png`.
- Focused material/imagery comparison: `D:/AfterCare/docs/card-comparison.png`.
- Browser viewport during the unscaled captures: 1400 × 1200; iPhone screen measured 393 × 852 CSS px at scale 1, Pixel screen 427 × 952. Screenshot dimensions match CSS dimensions (density 1).
- Reference normalization: left-screen content crop (65,125)-(313,684), 248 × 559 px, fitted with preserved aspect ratio into a 393 × 852 comparison region. Reference device chrome and the other two phones are excluded from content comparison. The runtime owns the implementation's device chrome.
- State: fictional report loaded, 19 fields reviewed, one flagged for clarification, plan saved. Pixel capture filters medications by “Amox”. Review capture shows the source quote, correction input and review actions after scrolling.

The reference and implementation were opened together in the full comparison board and the focused card board. This is a visual-language adaptation for AfterCare, not a pixel-identical clone of the reference medication app. The agreed changes include report review, a recovery-plan card, no anatomy/diagnosis interface and no active dose reminders.

## Required surfaces

- Typography: locally bundled Manrope provides the reference's rounded geometric sans character. Hierarchy, regular/medium/semibold weights, wrapping and line spacing were inspected. Small status labels are at least 9 px, medication detail text 10 px. Enlarging secondary labels further is residual P3 polish.
- Spacing/layout: translucent 24–29 px cards, consistent 23 px content insets, rounded floating navigation and unclipped primary controls. Content scrolls above persistent navigation. Both device presets retain their protected status, keyboard and navigation chrome.
- Colors/tokens: mint/sage ambient gradients, white translucent surfaces and thin borders, dark green actions and restrained amber review states. The custom background follows the selected reference direction.
- Images: the generated transparent medicine carton/blister is a real raster asset, with a sage band adapted to this product palette. Alpha, crop, sharpness and card placement were inspected. Standard controls use Phosphor library icons. Initials represent a user without an uploaded portrait; they are not a replacement portrait asset.
- Copy/content: screens describe report transcription and source review. Medication data comes from the local API. Unreviewed details carry review badges. Family explicitly explains its V2 status. No diagnostic anatomy screen or inferred dosage clock times are present.

## Fixes and final evidence

Before the formal comparison, initial browser checks found a misplaced navigation bar from an undefined safe-area variable and excess top-page scrolling during automated locator clicks. App-owned overflow and safe-area handling were corrected. Direct pointer navigation was then verified with device scroll offset 0. The protected runtime passes its integrity check.

The combined comparison also informed a more compact home heading and hero to bring medication content higher in the screen. The final home capture and comparison board show the revised proportions and floating bottom navigation. The small page image in review is supplemented by its exact text quote and an “Open full-size document” link; inline document disposition is covered by the API tests.

No actionable P0/P1/P2 visual findings remain for this first-slice scope.

## Interactions checked

- Open upload sheet and choose fictional report; baseline extraction produces 19 pending fields.
- Select a field and inspect highlighted source line.
- Correct a name, confirm it, flag age for clarification, and confirm remaining fictional fields.
- Save after 19/19 reviews; view the saved plan with flagged information excluded from the main confirmed fields.
- Open printable plan and inspect the separate clarification section.
- Reload and restart backend; saved plan persists.
- Filter medications by name; switch between iPhone and Pixel presets.
- Browser console error log was empty during final review.
- TypeScript/production build and mobile runtime integrity check pass. Eight backend tests pass. Build reports a non-blocking 516 kB client chunk warning; TestClient reports an upstream httpx deprecation warning.

## Functional boundaries and follow-up

- Local Tesseract is now installed in the project and tested with clean scanned PDF and PNG fixtures. Missing OCR still produces a clear setup error on other machines.
- A live Phi run returned 13 source-backed fields on one structured fictional report, compared with 19 baseline fields. A source-based medication-group normalization fix is regression-tested; this is not a clinical benchmark.
- Manual medication logging and follow-up booking/completion are now implemented. Caregiver permissions, reminders and contacts remain V2 work. No accounts or encryption at rest exist in the local single-user prototype.
- The supplied device frame is a development preview. A full-width desktop workspace is a future layout, not something verified in this first build.
- P3: further enlarge secondary labels and split the client bundle when serving beyond local development.

## Implementation checklist

- [x] Match the chosen mint/glass art direction with real imagery and library icons.
- [x] Verify upload/extraction/review/plan path and persistent data.
- [x] Preserve source evidence after corrections and block plans with pending fields.
- [x] Keep the application local and label prototype limits accurately.
- [x] Save visual evidence and compare full and focused regions.
- [x] Install OCR and test clean scan/photo fixtures.
- [ ] Expand held-out extraction evaluation.
- [ ] Build V2 workflows and the broader desktop layout.

## Second milestone review

final result: passed

Current evidence:

- `D:/AfterCare/docs/tracking-comparison.png`: original reference plus the new medication and follow-up screens in one comparison input.
- `D:/AfterCare/docs/tracking-meds.png`: medication list and today's activity count.
- `D:/AfterCare/docs/tracking-activity.png`: scrolled history with timestamp, note and undo fully above navigation.
- `D:/AfterCare/docs/tracking-visits.png`: booked follow-up and completed test.
- `D:/AfterCare/docs/tracking-booking-form.png`: persisted day/month/year selection and booking note.

The source crop and density normalization remain as above. All new content captures are 393 × 852 px at a measured 393 × 852 CSS device screen, scale 1, inside the 1400 × 1200 browser viewport. The frame and safe areas remain intact. The current fictional scanned report has all 19 fields reviewed, one active taken record, one undone skipped record, a follow-up booked for 24 Oct 2026 and a test marked completed.

The combined reference/current board and the full-size booking and activity captures were opened for review. Fonts remain locally bundled Manrope; form labels, facts and records use 10–13 px text. Card radii, mint/white surfaces, green actions and thin borders continue the reference style. Native selectors and Phosphor icons render cleanly. No new raster artwork or image placeholders were introduced. Copy distinguishes manual records and user-entered bookings from source instructions and reminders.

Two interaction findings were fixed before this final capture:

1. [P2, fixed] Dismissing the simulated keyboard could move a record/save button before its click completed. Action buttons now retain input focus during pointer-down, then dismiss the keyboard after the action fires. A skipped entry with a focused note was submitted with one click and undone in the browser.
2. [P2, fixed] The native date input conflicted with the simulated keyboard and did not retain date entry reliably. It was replaced by labeled day/month/year selectors. Choosing 24/Oct/2026, saving with a note, reopening and reloading all preserved the booking. The final booking-form capture shows the persisted values.

Verified in browser: scanned sample OCR with source-linked fields and an OCR warning; logging disabled before plan review; taken/skipped records with notes; undo; follow-up booking; test completion; persisted activity after reload; and access to all history controls by scrolling. Final browser error log was empty. Full backend suite: 17 passed, including actual OCR on both fixture formats. TypeScript/production build and protected mobile runtime checks pass. Existing upstream TestClient deprecation and client-chunk size warnings are non-blocking.

No actionable P0/P1/P2 findings remain in the second milestone. Existing P3 label-size and bundle-splitting refinements remain. OCR degradation evaluation, caregiver authorization, contacts, clinical reminder verification and the full-width desktop layout are outstanding product work, not represented as completed.

## Third milestone review

Added local account access, owned patient profiles/recovery episodes, saved contacts and a Today summary for the selected report. Retained the reference's mint background, Manrope typography, frosted cards, forest actions and floating navigation. The supplied mobile runtime remains unchanged.

Visual evidence uses the default browser viewport and includes the device frame:

- `D:/AfterCare/docs/accounts-sign-in.png`: local account entry and prototype boundary.
- `D:/AfterCare/docs/accounts-today.png`: profile/episode context, current report, pending-field count and today's record count.
- `D:/AfterCare/docs/accounts-contacts.png`: persisted fictional contact, phone link and no-sharing explanation.

Verified in browser: account creation; patient and recovery setup; fictional sample extraction into the selected episode; contact creation; second-patient setup with no first-patient documents or contacts; switching back; sign-out; sign-in after a backend restart; persisted profiles, reports and contacts; and reload with the remembered episode. Original pre-account reports were left unassigned. Final browser error log was empty. All 24 backend tests pass, including account isolation for source files/previews/plans/history/activity, session revocation and expiry, origin checks, patient/contact ownership and explicit legacy import. TypeScript/production build and all 28 protected runtime checks pass.

The contact sheet was shortened to avoid repeating the profile selector and migration controls while entering a contact. Sign-out now returns to the sign-in form. The Today summary identifies the active report and marks changed or unreviewed visit instructions for rechecking. An automation caveat remains in the supplied preview: locator auto-scrolling can scroll a hidden device ancestor and expose the hidden keyboard asset. Reloading and interacting with visible controls restored the correct frame; final captures use that normal state. No protected runtime files were changed.

No production-security or clinical-validation claim is made. Encryption at rest, account recovery, granular caregiver authorization, reminders and a standalone desktop layout remain outstanding. Today is scoped to the selected report; it does not aggregate an episode's documents. The first local account can explicitly import all legacy reports into one episode, so the user must check that they belong together.

## Fourth milestone review

Added patient-scoped caregiver invitations, acceptance/decline, owner revocation, view-only and view-and-record permissions, author labels on care records, and owner-visible access/activity history. Existing mint surfaces, Manrope type, forest actions and floating navigation remain the visual direction. No protected runtime file or device asset was changed.

Evidence:

- `D:/AfterCare/docs/caregiver-invitation-form.png`: exact username, permission and sharing scope before invitation.
- `D:/AfterCare/docs/caregiver-pending.png`: recipient invitation with scope, expiry and acceptance controls; no patient records available yet.
- `D:/AfterCare/docs/caregiver-active.png`: owner view of the accepted fictional grant, captured before revocation.
- `D:/AfterCare/docs/caregiver-activity.png`: fictional event recorded by caregiver-demo, with author, note and undo visible.
- `D:/AfterCare/docs/caregiver-audit.png`: invitation, acceptance, attributed event and revocation, including the caregiver's name.
- `D:/AfterCare/docs/caregiver-overview.png`: final owner controls after the test grant was revoked.

Browser checks used two fictional local accounts and a fresh synthetic reviewed report. Existing reports were not changed or imported. The full path was exercised: owner invitation, recipient sign-in/acceptance, recording permission, owner-only controls withheld, medication event with note and correct author, owner revocation and audit inspection. A live API check after UI revocation confirmed that the caregiver could no longer list patients/reports or fetch the report, original file, page preview, plan or activity. The owner still sees the historical event and audit. The test grant was left revoked.

Fixed during visual QA: shared permission context initially crowded the header and was moved into the scrollable content. Native focus scrolling could move the entire hidden-overflow phone screen and expose the hidden keyboard image; app code now keeps that viewport fixed through the public screen-portal reference. Content scrolling remains with MobileScroll. The final medication history capture shows status/header/navigation intact, with no exposed keyboard asset.

The focused search-to-Family check also caught a moving navigation bar when blur dismissed the keyboard before the click completed. Navigation buttons now retain focus on pointer-down and dismiss it when navigation fires. One tap from a focused search reached Family, with keyboard visibility false and device viewport scrollTop 0; the final overview capture shows the settled result. Final browser error log was empty.

Full backend suite: 33 passed. After adding caregiver names to the audit, all nine caregiver tests passed again. Coverage includes pending/expired/declined/revoked grants, every report read surface, owner-only edits, unrelated patients, activity roles, own-event undo, actor-bound idempotency, old-table migration and revocation between a read and write. TypeScript/production build and the 28-file runtime integrity check pass. Existing bundle-size and upstream TestClient warnings remain non-blocking.

Boundaries remain explicit: sharing works between accounts on this local installation; no email, SMS or remote synchronization. Accepted grants include future episodes for the named patient. Revocation blocks new requests and cannot recall copies. Access refresh uses focus and a 30-second visible-page check, not live push. Encryption, account recovery, broader extraction evaluation, clinically verified schedules and a standalone desktop layout remain outstanding.

## Prescription and dropdown fixes

The attached Carepatron prescription was readable by OCR but returned zero fields with the former narrow parser. The updated local reader identifies its prescription labels and ruled medication table, reads populated cells independently, and returns 12 pending source-backed fields. A live local Phi hybrid run returned the same 12 fields. No review was confirmed or schedule activated during browser verification. The original uploaded bytes remain available.

Evidence:

- `D:/AfterCare/docs/fixed-profile-dropdown.png`: mint select menu with rounded rows, selected-state checkmark and matching trigger width.
- `D:/AfterCare/docs/fixed-prescription-fields.png`: complete frequency, duration, medication warning and remarks from the supplied image.
- `D:/AfterCare/docs/fixed-prescription-source.png`: the original instruction cell highlighted with its exact extracted text in the editor.

App-owned profile, recovery, engine, caregiver-permission and appointment date selectors share CareSelect. Verified pointer and keyboard profile selection, focus return, Escape closing only the menu, and selection updating the correct recovery context. Select 2.3.3 shares the existing dialog's dismissal/focus primitives; the initial newer dependency introduced duplicate layers and was replaced, then Vite's stale dependency cache was rebuilt. Trigger/menu styles apply to phone portals as well as the app root. The device-picker runtime remains unchanged.

The exact JPG was uploaded through the browser into a separate `Karlene Hizon (sample)` profile and `Prescription reader check` episode. All 12 details remained pending. The source preview highlights the instruction cell rather than the neighboring frequency column, and keeps the full maximum-dose warning and separate remarks. No prior reports were changed or imported. Final browser error log was empty.

Full backend suite: 39 passed. New coverage includes the exact attachment, selectable PDF and scanned multi-row tables, column/row alignment, concentration and conditional-frequency preservation, zero-field retry, original-file/timestamp preservation and concurrent retry protection. Caregiver permissions also cover the new owner-only retry endpoint. TypeScript/production build and 28-file mobile runtime integrity checks pass.

Limitations: the reader supports a conservative subset of labeled/ruled layouts. These checks do not establish accuracy on arbitrary, noisy, rotated, handwritten or multilingual prescriptions. Existing reports with extracted details are not silently replaced; only zero-field reports offer the safe retry. Source review remains transcription review only.

## Report export and archive milestone

Reports now has owner-only three-dot actions, a local ZIP download and a reversible archive confirmation. Archived reports are listed within the selected recovery with a restore action. The sheets retain the mint palette, frosted surfaces, Manrope typography and supplied phone-scoped controls. No dependencies or protected runtime files were changed.

Evidence:

- `D:/AfterCare/docs/report-options.png`: iPhone report actions and export limitations.
- `D:/AfterCare/docs/report-archive-confirmation.png`: retained evidence, caregiver restrictions and cancellation before archiving.
- `D:/AfterCare/docs/report-archives.png`: owner restore action for an archived fictional report.
- `D:/AfterCare/docs/report-options-pixel.png`: the same options in the supplied Pixel preset.

Browser verification created one fresh fictional sample, downloaded its ZIP, cancelled an archive, then archived and restored that sample. The active list omitted it while archived, the archive list contained it, and the archive list was empty after restoration. Reload preserved the restored report. ZIP original bytes matched the stored file; the restored report payload matched its exported state, with all 19 fields still pending and no plan saved. Prior reports, legacy imports and caregiver grants were not changed. Device selection returned to iPhone after Pixel verification. The preview remains open.

All 52 backend tests pass, including owner/caregiver/unrelated-account restrictions, every archived read/write surface, current-grant restoration, original/review/activity preservation, ZIP scope and safe member names, undone-event attribution, missing-source failure, archive/write races, stale plan saves and concurrent field corrections. Production build and all 28 runtime integrity checks pass. The existing bundle-size and upstream TestClient deprecation warnings remain non-blocking.

ZIP copies are unencrypted and cannot be imported as backups. They contain current visit details and change audit, not every previous booking/note. Archiving retains local files and cannot recall existing copies. Encryption, permanent deletion, account recovery, remote hosting and clinically verified schedules remain separate work. Architecture and limitations are documented in the root README and spec.

## Daily care workflow

Today now leads with an action determined by the selected report: add/read a document, review pending details, save the transcription, open unresolved care questions or record/view care activity. Report selection includes timestamps and review state. Account settings, patient/recovery selection and legacy import have separate panels; forms omit unrelated selectors. The saved plan is labeled reviewed instructions. The bell is explicitly In-app updates and explains that timed/background medication alerts are unavailable.

The existing mint/forest palette, Manrope typography, rounded frosted surfaces and floating navigation remain. Today's decorative medicine hero was replaced by one focused action card so care tasks appear earlier. No protected runtime files or dependencies changed.

Evidence:

- `D:/AfterCare/docs/daily-next-step.png`: source-linked care-question action for a fictional recovery.
- `D:/AfterCare/docs/daily-visits-activity.png`: separate source and recorded booking dates, past-booking status check, today's booking and manual activity count. Captured before completing the fictional test.
- `D:/AfterCare/docs/daily-care-questions.png`: flagged detail, original excerpt, page and source-navigation control.
- `D:/AfterCare/docs/daily-patients.png`: patient/recovery definitions and selectors without sign-out/import controls.
- `D:/AfterCare/docs/daily-account.png`: account and local-data controls.
- `D:/AfterCare/docs/daily-updates.png`: explicit notification limitation and unresolved-question link.
- `D:/AfterCare/docs/daily-pixel.png`: Today in the supplied Pixel preset; returned to iPhone afterward.

Browser verification used a separate fictional patient/recovery and sample report. Its transcription has one flagged frequency, 18 confirmed details, one manual medication event and two user-booked visits. Opening the question navigated to the exact Medication 2 / Frequency source preview without modifying its flag or review history. A past booking asked for its outcome, and marking the fictional test completed removed it from Today. The separate booking for today remained. Switching to an empty recovery showed no prior questions, bookings or activity; switching reports changed the next action correctly. Recovery creation could be opened and cancelled without repeated selectors. Existing reports, caregiver grants and unassigned legacy documents were not changed.

Six frontend behavior tests pass via `npm run test:care`. They cover review/save gating, preserved question evidence, source dates not becoming bookings, completed/changed-source visit behavior, unreviewed follow-ups, local-day event counts and the 100-record limit. The helper is a read-only derivation, with no schedule or record writes. Existing backend permissions and integrity guards remain unchanged. Production build and all 28 protected runtime checks pass; the existing bundle-size warning remains non-blocking.

Limits: Today covers one selected report, uses only the latest 100 active medication events, and needs manual refresh for external care changes. Questions are a consultation aid; they do not resolve clinical uncertainty or establish verification. A clinical-verification workflow and timed/background alerts remain unimplemented. Automated browser coverage for activity-load failures was not added; the UI has explicit loading/error states and a retry action.

## AfterCare Local 1.0 release

The selected release target is a local portfolio/demo app. Home now emphasizes a direct manual medicine-recording action when eligible, visible Add report, a compact attention card, one visit task and recent activity. Full medicine lists and support cards no longer repeat on Home. Recording eligibility requires a named medicine, confirmed fields, unique labels and a saved transcription; server permissions and integrity checks remain authoritative.

Account security adds current-password-protected password changes, one-time recovery codes and a recovery form with confirmation. The code is displayed once, copied only on user action, never stored in browser storage, and cleared from UI state on dismissal. Password changes invalidate earlier sessions and recovery codes. Recovery consumes its code atomically and signs out all sessions. Browser QA inspected blank forms and recovery/back-to-sign-in navigation without changing existing credentials or generating a persistent recovery credential. Credential mutation, code rotation/replay and concurrent consumption were tested with isolated accounts.

Offline encrypted installation backups restore into a new folder. Tests preserve source bytes, saved transcription, reviews and undone care events while removing sessions/codes and revoking accepted/pending caregiver grants. Wrong keys, changed ciphertext, missing sources, unsafe archive paths, occupied installations and overwrite attempts fail explicitly. Backup encryption does not cover live storage. No installation-wide backup was made from existing user records during verification.

The built frontend and API now run together at `http://127.0.0.1:8000/` through `scripts/run.py`; development remains on 5173. A local installation lock prevents simultaneous servers/backup operations. The occupied-port guard was exercised before stopping the previous known development API. The protected runtime is unchanged. No deployment was performed.

Evidence:

- `D:/AfterCare/docs/release-home.png`: final simpler Home with manual recording and Add report.
- `D:/AfterCare/docs/release-medicine-picker.png`: direct chooser for source-backed medicines.
- `D:/AfterCare/docs/release-account-security.png`: password/recovery controls with no secrets entered.
- `D:/AfterCare/docs/release-recovery-form.png`: anonymous recovery form on localhost, without affecting the signed-in demo session.

The complete release-check command passed 65 backend tests, six workflow tests, the production build and all 28 runtime hashes. After final UI cleanup/version alignment, workflow tests and production/runtime checks passed again. Browser checks exercised authenticated API access from the built single-origin app, recovery navigation, selecting the isolated fictional recovery and opening the medicine record form with reviewed details and existing activity. No new medication event was recorded in existing user data during release QA. Build-size and upstream TestClient deprecation warnings remain non-blocking.

This finishes the documented local release scope, not clinical V2. Real clinician verification, active schedules/timed/background alerts, encrypted live storage, permanent deletion, remote deployment and broader clinical extraction evaluation remain unimplemented. The README states these limits and contains setup, backup/restore and interview-oriented architecture details.


## V2 verification — 2026-10-18

- Scope: separate clinician authorization/consent/review desk, immutable approved proposals tied to source revision, date/time-zone schedules, taken/skipped/undo/history/snooze, in-app due list and optional Web Push, whole-database/original-file encryption, fresh-key backup restore, permanent archived-report deletion and hosting configuration.
- Final release gate: 90 backend tests, 6 frontend behavior tests, TypeScript/production build and all 28 protected runtime hashes passed. Expected warnings: upstream TestClient/httpx deprecation and an approximately 619 KB JavaScript bundle. No browser error logs in the final preview.
- Browser walkthrough used newly created fictional patient/clinician accounts. Inspected original-page preview and reviewed transcription, submitted an explicitly simulated approval note/attestation, then verified patient schedule visibility, taken, undo and ten-minute snooze. No real clinician was provisioned; demo roles cannot approve uploaded documents. Actual browser notification permission and live push-provider delivery were not exercised. A separate test encrypts/decrypts a real Web Push payload without network I/O, and dispatch tests cover approval/access rechecks, retries, completion and snooze.
- Preserved all 22 pre-upgrade report payloads and original byte streams exactly; the added fictional report makes 23 encrypted originals. No orphan source files or unencrypted managed originals were found. The pre-upgrade rollback backup is encrypted; its passphrase is Windows-user protected. Existing credentials and patient reviews were retained.
- Checked iPhone and Pixel 10 at the normal supplied preview viewport, retaining runtime chrome, scroll, navigation and styled menus. Restored iPhone. Final preview stays open at http://localhost:8000/ on the fictional V2 patient account.
- Evidence: `docs/v2-home.png`, `docs/v2-approved-schedule.png`, `docs/v2-reminders.png`, `docs/v2-pixel.png`.
- Operator prerequisites: independently verify real clinician identities before authorizing their accounts; provide target hosting/domain/secrets and run deployment/restore/permission/push smoke tests. Docker is not installed here, so no container/TLS/public deployment claim is made. OCR regressions are not clinical validation; no interaction or contraindication engine is provided. All document processing remains local.
