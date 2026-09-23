# Complaints Mini App User Guide

## About this guide

The Complaints Mini App is the staff workspace for recording, reviewing,
resolving, reopening, reporting, and following up customer complaints from
Telegram.

This guide explains the app in everyday language. It is intended for Complaint
Officers, Complaint Managers, HomeBiogas resolution staff, IT staff, and other
authorized users. What you see depends on your assigned role and work scope, so
some buttons described here may not appear on your account.

The examples and screenshot labels in this guide must use training data only.
Never place real customer names, phone numbers, national IDs, complaint text,
or attachments in training screenshots.

## Contents

1. [What the Mini App does](#1-what-the-mini-app-does)
2. [Roles and access](#2-roles-and-access)
3. [Opening the Mini App](#3-opening-the-mini-app)
4. [The Complaints list](#4-the-complaints-list)
5. [Recording a new complaint](#5-recording-a-new-complaint)
6. [Complaint detail](#6-complaint-detail)
7. [Completing missing information](#7-completing-missing-information)
8. [Resolving a complaint](#8-resolving-a-complaint)
9. [Reopening a complaint](#9-reopening-a-complaint)
10. [Attachments and the secure file viewer](#10-attachments-and-the-secure-file-viewer)
11. [Data Overview and reports](#11-data-overview-and-reports)
12. [Downloading the complaints workbook](#12-downloading-the-complaints-workbook)
13. [Google Sheets synchronization](#13-google-sheets-synchronization)
14. [Good working practices](#14-good-working-practices)
15. [Errors and troubleshooting](#15-errors-and-troubleshooting)
16. [Quick reference](#16-quick-reference)
17. [Screenshot checklist](#17-screenshot-checklist)

---

## 1. What the Mini App does

The Mini App gives staff one controlled place to manage complaints from the
time they are recorded until the customer issue is resolved.

It helps the business to:

- give every complaint a short, memorable reference such as `CMP-1042`;
- keep customer details, complaint facts, attachments, and actions together;
- prevent complaints from disappearing in chat history;
- show which complaints are still open and which are closed;
- preserve a dated history of resolutions and reopenings;
- allow management to see complaint patterns across branches and categories;
- keep the operational Google Sheet register updated without making the Sheet
  a second source of truth; and
- maintain an audit trail showing who performed each important action.

The app is not a public customer portal. It is for authorized staff using their
own Telegram identity.

### The complaint lifecycle

```text
Record complaint -> Open -> Resolve -> Closed
                         ^              |
                         |--- Reopen ---|
```

A historical complaint with missing required identifiers may first show
**Needs More Information**. After an authorized user completes the missing
details, it returns to **Open**.

---

## 2. Roles and access

The app shows only the screens and actions permitted for the signed-in user.
The table below describes the standard role setup. Access may be narrowed by
group or branch, and an approved policy change may adjust a role's permissions.

| Role | What the role normally does | Main business reason |
| --- | --- | --- |
| Complaint Officer | Views the complaint queue, records new complaints, completes missing intake details, and views or adds evidence. | Ensures complaints enter the organization with complete, usable information. |
| Complaint Manager | Performs Officer work, reopens complaints when the issue continues, and handles operational follow-up such as synchronization escalation. | Protects workflow quality and ensures incorrectly closed complaints return to active work. |
| HomeBiogas resolution staff | Views complaints, investigates them, adds supporting evidence, and records the final resolution. | Ensures closure is performed by the team responsible for the customer outcome. |
| IT | Views the queue, sees the organization-wide Data Overview, exports the governed complaints workbook, and supports failed Sheet publication. | Provides controlled reporting and technical recovery without taking over business resolution decisions. |

An active technical Superuser may have audited break-glass access. This is not
the same as a normal business role.

### If a button is missing

A missing **New Complaint**, **Resolve Complaint**, **Reopen Complaint**,
**Data Overview**, or **Download Complaints** button usually means the action is
not part of your current role or scope. It is not normally a display fault.
Ask your Manager or IT to check your assigned access rather than using another
person's account.

---

## 3. Opening the Mini App

1. Open the correct authorized Telegram group or staff launcher.
2. Open the pinned **JBL Apps** message.
3. Tap **Complaints**.
4. Wait for your name and role to appear under the page title.

Always enter through the approved Telegram launcher. A copied browser link may
not include the correct group and may fail to open the complaint queue.

The refresh icon in the top-right corner reloads the latest confirmed data.
Use it if another staff member has just changed a complaint or if your network
temporarily disconnected.

> **Screenshot 1 — App opening and header**
> Add a mobile screenshot showing the Complaints title, signed-in user/role,
> and refresh icon. Use synthetic data.

### Business benefit

Opening from Telegram ties the session to the staff member and the correct
complaint group. This reduces accidental cross-group access and ensures actions
are attributed to the right person.

---

## 4. The Complaints list

The first screen is the working complaint queue.

### Status tabs

- **Open** shows all complaints that still require attention, including
  reopened complaints and historical records marked Needs More Information.
- **Closed** shows resolved complaints.
- **All** shows both open and closed complaints.

The number beside each tab is the current number of complaints in that view.

### Complaint cards

Each row shows the information needed to identify the complaint quickly:

- list position and complaint reference;
- customer name;
- phone number or customer ID;
- complaint type;
- branch;
- age or completion state; and
- status, including a Needs More Information warning where applicable.

Tap anywhere on a complaint row to open it.

### Search

Use the search box to find a complaint by:

- complaint reference;
- customer name;
- Customer National ID;
- phone number; or
- words in the complaint description.

Search applies to the selected Open, Closed, or All tab. If nothing appears,
clear the search and check the other status tabs.

### Pages

The app shows ten complaints per page. Use **Previous** and **Next** at the
bottom of the list to move through additional results.

> **Screenshot 2 — Complaint queue**
> Add a mobile screenshot showing the Open/Closed/All tabs, count pills,
> search field, complaint rows, and pagination.

### Business benefit

The queue puts unresolved work first while keeping closed history accessible.
Short references and search remove the need to scan Telegram messages or Sheet
rows to find one customer complaint.

---

## 5. Recording a new complaint

Users with permission see **New Complaint** at the top of the complaint list.

Tap it to open **Record a New Complaint**.

### Required information

Complete the following fields:

- **Customer name** — the customer's full name;
- **Primary Phone Number** — a valid Kenyan mobile number;
- **Customer National ID** — numbers only;
- **Branch**;
- **County**;
- **Constituency** — choices appear after the county is selected;
- **Village**;
- **What happened?** — a clear description of the issue; and
- **Complaint Type** — the category that best represents the main problem.

The **Secondary Phone No** is optional. If entered, it must be a valid Kenyan
number and must be different from the primary number.

The customer name is tidied into normal name capitalization when the complaint
is submitted. National IDs keep any leading zeroes.

### Choosing the location fields

Select Branch, County, and Constituency from the available choices. These
choices are controlled centrally so reports use consistent place names.

If Constituency is disabled, choose the County first. If a location you expect
is absent, do not select a knowingly incorrect place; report the missing option
to your Manager or IT.

### Complaint type suggestion

After you describe what happened, the app may suggest a complaint type. Tap
the suggestion to use it, or select a different category if the suggestion
does not represent the main issue.

The suggestion is an aid, not an automatic business decision. The user remains
responsible for the final category.

### Optional GPS location

Tap **Use My Current Location** when the customer's or incident location is
useful to the complaint.

1. Allow Telegram or the browser to access location.
2. Wait for **Location Captured** and the coordinates.
3. Continue completing the form.

GPS is optional. A complaint can still be recorded without it.

### Optional photos or PDF documents

Use **Take Photos** or **Upload Files** to attach supporting evidence. You can
preview and remove selected files before submitting.

Current limits are shown in the app. The standard limits are:

- up to 10 files;
- up to 10 MB per file;
- up to 30 MB in total; and
- JPEG, PNG, WebP, or PDF files.

### Submitting

Review the details and tap **Submit Complaint** once. Keep the Mini App open
while the button shows that it is creating or saving.

After a successful save:

- the complaint receives its permanent complaint reference;
- the complaint detail page opens;
- the main complaint record is already safe in the system; and
- evidence upload and Google Sheet publication may finish immediately after
  the main save.

If the app says the complaint was saved but evidence or Sheet publication
needs attention, do **not** create the complaint again. Use the displayed
reference and follow the recovery guidance in this manual.

> **Screenshot 3 — New complaint form**
> Add a full mobile screenshot showing customer details, controlled location
> fields, complaint description/type, GPS, evidence, and Submit Complaint.

> **Screenshot 4 — Category suggestion and captured location**
> Add a close screenshot showing a category suggestion and the successful
> Location Captured state.

### Business benefit

Required identifiers reduce duplicate or untraceable complaints. Controlled
locations and categories improve branch reporting, while optional GPS and
evidence help resolution staff verify what happened.

---

## 6. Complaint detail

The detail page is the complete working view for one complaint.

### Complaint summary

The top section shows:

- complaint reference;
- customer name;
- status;
- Needs More Information warning, where applicable;
- phone number and Customer National ID;
- complaint description;
- complaint type;
- branch and reported date;
- source information; and
- Google Sheet synchronization status.

Use the back arrow to return to the Complaints list or Data Overview from which
you opened the complaint.

### Resolution History

For a previously resolved or reopened complaint, **Resolution History** shows:

- what was done;
- who resolved it and when;
- why it was later reopened, if applicable; and
- who reopened it and when.

Older history is retained. Reopening does not erase the earlier resolution.

### Attachments

The **Attachments** section lists the complaint's successfully retained files.
Tap **View in app** to open an authorized secure preview.

### Complaint History

The history lists important actions in time order, such as:

- complaint recorded;
- more information requested;
- required details completed;
- complaint resolved; and
- complaint reopened.

Each item identifies the staff member and date/time where available.

> **Screenshot 5 — Complaint detail**
> Add a full mobile screenshot showing the complaint summary, status, Sheet
> Sync line, Resolution History, Attachments, and Complaint History.

### Business benefit

The detail page gives staff the effective current outcome and its supporting
history without requiring them to interpret raw Sheet rows or Telegram posts.

---

## 7. Completing missing information

Some older complaints may show **Needs More Information** because required
customer information was not captured during the original intake.

An authorized Officer or Manager sees **Complete Legacy Case Details**.

1. Confirm or enter the primary phone number.
2. Confirm or enter the Customer National ID.
3. Select the Complaint Type.
4. Tap **Complete Details**.

Existing verified information may be read-only. After the details are saved,
the complaint returns to **Open** and can follow the normal resolution process.

> **Screenshot 6 — Complete Legacy Case Details**
> Add a screenshot showing a Needs More Information complaint and the fields
> used to complete it.

### Business benefit

This recovers usable historical complaints without changing the original
source message or silently inventing missing identifiers.

---

## 8. Resolving a complaint

Authorized HomeBiogas resolution staff see **Resolve Complaint** on an open or
reopened complaint.

### Before resolving

Confirm that:

- the complaint belongs to the customer shown;
- the reported issue has actually been addressed;
- the outcome is known;
- any useful supporting evidence has been selected; and
- the resolution note is clear enough for another staff member to understand.

### Resolution note

Write what was done and the outcome. Include:

- the action completed;
- when it was completed;
- the resulting customer outcome; and
- whether the customer confirmed that the issue was resolved, where known.

Avoid vague notes such as “done,” “sorted,” or “resolved.”

### Submit the resolution

1. Enter the Resolution Note.
2. Optionally take photos or upload supporting files.
3. Tap **Resolve Complaint** once.
4. Wait for the success message and the status to change to **Closed**.

The resolution is an audited action. It records the responsible user and is
added to complaint history.

> **Screenshot 7 — Resolve Complaint**
> Add a screenshot showing the resolution-note guidance, optional evidence,
> and Resolve Complaint button.

### Business benefit

Restricting final resolution to the responsible team and requiring a meaningful
note prevents unsupported closure and produces evidence that management can
review later.

---

## 9. Reopening a complaint

Complaint Managers can reopen a closed complaint when the issue was not fully
resolved or has returned.

1. Open the closed complaint.
2. Review the previous resolution.
3. In **Reopen Complaint**, explain why the complaint requires more work.
4. Tap **Reopen Complaint**.

The status becomes **Reopened**, and the case returns to the Open queue. The
previous resolution remains visible.

Do not create a new complaint merely because a customer disputes the outcome
of the same unresolved issue. Reopen the existing complaint so its full history
stays together. A genuinely separate new incident may be recorded as a new
complaint.

> **Screenshot 8 — Reopen Complaint**
> Add a screenshot showing the previous resolution and required reopening
> reason.

### Business benefit

Reopening preserves the complete customer journey and avoids making performance
reports look better by incorrectly treating unfinished work as a new case.

---

## 10. Attachments and the secure file viewer

Attachments may be added while recording or resolving a complaint.

### Taking photos

1. Tap **Take Photos**.
2. Allow camera access when asked.
3. Tap **Take Photo** for each image required.
4. Tap **Done** when finished.

Nothing uploads until the complaint or resolution is submitted.

### Reviewing selected files

Before submission, tap **View** beside a selected file. For selected photos you
can:

- move to the previous or next image;
- pinch to zoom;
- retake the selected photo; or
- delete it from the pending selection.

### Viewing saved evidence

On complaint detail, tap **View in app**. The file is loaded from controlled
storage only after your current access is checked. Images support swipe and
pinch gestures. PDFs open in the secure in-app preview.

Some older file types may be retained for audit but cannot be previewed inside
the current Mini App.

> **Screenshot 9 — Camera and selected evidence**
> Add two screenshots: the full-width camera view and the selected-file viewer
> with previous, next, retake, and delete controls.

> **Screenshot 10 — Saved evidence preview**
> Add a screenshot of synthetic saved image or PDF evidence in the secure
> viewer. Do not use customer evidence.

### Business benefit

Evidence is kept with the complaint and access is rechecked whenever it is
opened. This is safer and more auditable than circulating customer files in
uncontrolled chats or personal storage.

---

## 11. Data Overview and reports

The **Data Overview** tab is normally visible to authorized IT/reporting users.
It is read-only and covers complaints across authorized complaint groups.

### Summary metrics

The top metrics show the current total and the main complaint states, including
pending, resolved, and Needs More Information counts.

### Charts

**Complaints by Type** can be shown as a bar or pie chart.

**Complaints over Time** can be grouped by:

- day;
- week;
- month; or
- year.

Choose a wider grouping or a narrower date range when a chart contains too
many periods.

### Report filters

The report can be narrowed using:

- search;
- status;
- branch;
- complaint category; and
- date reported, using any time, a selected month, or a custom date range.

Tap **Show Results** after changing filters. Tap **Reset Filters** to return to
the unfiltered report.

### Complaint table

The table shows detailed complaint rows. You can:

- scroll horizontally to see additional columns;
- sort supported columns;
- move between pages;
- change **Table size** using minus, reset percentage, and plus; and
- open a complaint row for more detail.

On a phone, horizontal table scrolling is expected because the report contains
more columns than can fit safely on one narrow screen.

> **Screenshot 11 — Data Overview summary**
> Add a screenshot showing the global metrics, complaint-type chart, and trend
> chart.

> **Screenshot 12 — Report filters**
> Add a screenshot showing status, branch, category, and date controls.

> **Screenshot 13 — Complaint report table**
> Add a screenshot showing the table, horizontal-scroll area, table-size
> controls, and pagination.

### Business benefit

Data Overview turns individual complaints into operational insight. Management
can identify recurring complaint types, branch patterns, changes over time,
and data-quality gaps without changing live complaint records.

---

## 12. Downloading the complaints workbook

Authorized users see **Download Complaints** in Data Overview.

The download is intentionally separate from the on-screen filters. It contains
the governed complaint register across all complaint groups, not merely the
rows currently visible on screen.

1. Tap **Download Complaints**.
2. Read the confirmation showing how many complaints will be included.
3. Tap **Download Complaints** again to confirm.
4. Accept Telegram's download prompt.
5. Open the file from the success panel or your device Downloads folder.

The generated workbook contains fields such as complaint reference, dates,
status, customer details, location, reporter, complaint type and description,
GPS link, resolution details, days open, and resolution history.

Names and other applicable text are standardized in uppercase in the export,
dates use the governed workbook format, and GPS values are clickable links.

The download is audited and may contain sensitive personal data. Store it only
in an approved location and do not forward it through personal accounts.

> **Screenshot 14 — Export confirmation and download ready**
> Add screenshots of the export confirmation and the Download ready
> panel.

### Business benefit

The explicit all-data confirmation prevents a user from mistaking a filtered
screen for the export's scope. Audited exports support controlled management
review without turning the Mini App into an unrestricted report builder.

---

## 13. Google Sheets synchronization

### What synchronization means

The Mini App keeps the organization's configured Google complaint register up
to date. The Sheet is a convenient operational and reporting view. The Mini
App's main database remains the authoritative complaint record and audit
history.

Do not treat a temporary Sheet delay as a lost complaint.

### What is sent to the Sheet

Depending on the configured register, synchronization publishes the complaint's
main operational fields, including:

- complaint reference;
- date reported and current status;
- customer name, National ID, and phone numbers;
- county, constituency, village, and branch;
- reporting staff member;
- complaint type and description;
- GPS link, if captured;
- latest resolution details and accumulated resolution history;
- date resolved; and
- days open.

### When synchronization happens

- **New complaint:** the complaint is first saved safely in the Mini App, then
  published to the configured Sheet.
- **Missing details completed:** the saved identifiers, category, and Open
  status are published.
- **Complaint resolved:** Closed status, resolution, resolution date, history,
  and days open are published.
- **Complaint reopened:** Reopened status and the updated resolution history
  are published, and the resolved date is cleared where appropriate.

### Understanding the Sheet Sync label

| Label | Meaning | What the user should do |
| --- | --- | --- |
| **Synced** | The current complaint information was published successfully. | No action is required. |
| **Pending** | The complaint is saved, but publication has not finished. | Wait briefly, refresh, and check again. Do not create a duplicate complaint. |
| **Failed** | The complaint or action is saved, but the last publication attempt did not succeed. | Keep the complaint reference and report it to a Manager or IT for retry. |
| **Not enabled** | This complaint group is not currently configured to publish to a Sheet. | Continue using the Mini App. Ask IT only if Sheet publication was expected. |

Manager/IT recovery checks current access and retries the same complaint. It
does not create a new complaint or replace the complaint's audit history.

### Important working rule

Use the Mini App for complaint status, resolution, reopening, and missing-detail
work. Manual changes made only in Google Sheets do not create the same staff
audit trail and may drift from the authoritative complaint record.

### Sheet screenshots to add

The following placeholders are intentionally reserved for the manual Sheet
screenshots you will add:

> **Screenshot 15 — Google complaint register overview (manual image)**
> Show the Sheet title, frozen header, complaint reference, status, customer,
> location, category, and resolution columns. Blur or replace customer data.

> **Screenshot 16 — A synchronized complaint row (manual image)**
> Show one synthetic complaint after successful creation, with its complaint
> reference matching the Mini App.

> **Screenshot 17 — Resolved and reopened rows (manual image)**
> Show the Closed/Reopened status, resolution details/history, date resolved,
> days open, and GPS link behavior using synthetic records.

### Business benefit

Staff who rely on the register receive an updated familiar view, while the
business retains one governed workflow record and a reliable audit trail.
Separating “saved” from “published” also prevents a Google outage from erasing
work already completed by staff.

---

## 14. Good working practices

### Write useful complaint descriptions

State what happened, where it happened, what the customer expected, and any
important dates. Avoid conclusions that have not been verified.

### Write complete resolution notes

A good note answers: what was done, when, what changed, and whether the customer
accepted the outcome.

### Protect customer information

- Use only your own Telegram account.
- Do not share complaint screenshots outside approved work channels.
- Do not download or forward evidence unless required for your role.
- Store exported workbooks only in approved organizational storage.
- Never use real customer data in training screenshots.

### Avoid duplicates

- Search by phone number, National ID, and customer name before creating a
  complaint when duplicate intake is a concern.
- Tap submit once and wait on a slow connection.
- If a complaint reference appears, the complaint exists even when evidence or
  Sheet publication still needs attention.
- Reopen the same unresolved incident instead of creating a second complaint.

### Refresh before consequential actions

If the complaint has been open on your screen for a long time, refresh it
before resolving, reopening, or completing details. The app will protect
against overwriting a newer staff action, but refreshing reduces conflicts.

### Pay attention to the close warning

Telegram may warn you before closing when a form, note, or selected attachment
has not been submitted. Return to the Mini App if you still need that work.
Leave only when you deliberately want to discard the unsaved entry. A warning
protects the current screen; it is not confirmation that a draft was saved.

---

## 15. Errors and troubleshooting

### First steps for any problem

1. Read the complete message shown in the app.
2. Note the complaint reference and any error **Reference** displayed.
3. Check whether Telegram has an internet connection.
4. Use **Try Again** when offered.
5. Refresh or close and reopen the Mini App from the approved launcher.
6. Do not repeatedly create or submit the same action.
7. If the problem continues, send IT the complaint reference, error reference,
   time, screen name, and a screenshot that does not unnecessarily expose
   customer data.

### Access and opening problems

| What you see | Likely reason | Remedy |
| --- | --- | --- |
| The launcher is missing its Telegram group or the queue will not load | The app was opened from a copied/direct link. | Close it and reopen **Complaints** from the pinned JBL Apps launcher in the correct group. |
| Telegram authentication is required or the session expired | The Telegram launch information is missing or old. | Close the Mini App completely and reopen it from Telegram. |
| Your account is not configured or permission is denied | Your staff access is inactive, out of scope, or does not include that action. | Ask your Manager or IT to check your current role, group, and branch assignment. Do not borrow another user's account. |
| A screen or button is missing | Your role does not receive that feature. | Check the role table in this guide. Escalate only if your assigned duties require the action. |
| “Outdated client” or a prompt to reopen | Telegram has retained an old version of the app. | Close the Mini App, reopen from the launcher, and update Telegram if requested. |

### Queue, search, and report problems

| What you see | Likely reason | Remedy |
| --- | --- | --- |
| No complaints match this view | Search text or the selected status tab excludes the complaint. | Clear search, check Open/Closed/All, and move through pages. |
| Counts look older than another user's screen | Your screen has not refreshed since their update. | Tap refresh. |
| Data Overview is unavailable | Your role does not include organization-wide reporting. | Use the complaint queue, or request the report from authorized IT/reporting staff. |
| A chart says there are too many time periods | The chosen date range is too wide for Day or Week grouping. | Narrow the date range or change grouping to Month or Year. |
| The report table looks wider than the phone | Detailed columns require horizontal space. | Swipe horizontally inside the table and use Table size controls. This is expected. |

### New complaint and field-validation problems

| What you see | Likely reason | Remedy |
| --- | --- | --- |
| A field is highlighted as required | The field is blank or contains only spaces. | Enter the requested information and submit again. |
| Customer National ID must contain numbers only | Letters, punctuation, or spaces were entered. | Enter the digits exactly as shown on the customer's ID. |
| Enter a valid Kenyan phone number | The number has the wrong length or prefix. | Check the number and enter a valid Kenyan mobile number, such as `07…` or `2547…`. |
| Primary and secondary numbers must be different | The same number was entered twice. | Correct the secondary number or leave it blank. |
| Constituency remains disabled or invalid | County has not been selected, choices are still loading, or the combination is unavailable. | Select Branch and County, wait for choices, then select a valid Constituency. Report a genuinely missing location. |
| Complaint type suggestion is wrong | Suggestions are based on the description and are not final decisions. | Select the correct complaint type manually. |
| Complaint type suggestion does not appear | The description is too short, no confident match exists, or the suggestion service is temporarily unavailable. | Continue and select the complaint type yourself. |

### GPS, camera, and attachment problems

| What you see | Likely reason | Remedy |
| --- | --- | --- |
| Location is unavailable or not captured | Device GPS is unavailable, permission was denied, or the request timed out. | Enable location for Telegram/browser, move to a place with a better signal, and tap **Try Location Again**. GPS is optional. |
| Camera will not open | Camera permission is denied or another application is using it. | Allow camera access, close other camera apps, and retry. Alternatively use **Upload Files**. |
| Unsupported evidence type | The selected file is not JPEG, PNG, WebP, or PDF. | Convert or select a supported file. |
| File exceeds the size limit | A file is larger than the displayed per-file limit. | Reduce the file size or select a smaller file. |
| Too many files or total size exceeded | The pending selection exceeds the displayed count or total limit. | Remove unnecessary files or split the evidence across the permitted complaint actions. |
| Secure evidence cannot be opened | Storage is temporarily unavailable, access changed, or an older file type cannot be previewed. | Close the viewer and retry. If it persists, give IT the complaint and file name. |
| A PDF cannot be prepared for viewing | The secure PDF preview could not be generated. | Retry later and report the complaint/file reference if it continues. |

### Saving, conflict, and status problems

| What you see | Likely reason | Remedy |
| --- | --- | --- |
| The button stays in a saving state | The network or file upload is slow. | Keep the app open and wait. Do not tap repeatedly. If it ultimately fails, use the offered retry. |
| Telegram warns before closing | The app has an unfinished form, note, file selection, or operation. | Return to the Mini App and submit or clear the work. Leave only if you intend to discard it. |
| Information entered in a form disappeared after closing the app | The form had not been submitted; close protection is not a saved draft. | Re-enter the information and submit it. Keep the app open until the confirmed result appears. |
| Complaint created, but evidence or Sheet publication needs attention | The main complaint was saved, but slower external work did not finish. | Do not recreate it. Keep the complaint reference, refresh, and contact Manager/IT if Failed or Pending persists. |
| “This complaint changed while you were working” | Another staff member saved a newer action first. | Read the winning update, use **Copy My Draft** if needed, then tap **Review Latest Complaint** before deciding whether another action is still necessary. |
| Resolve Complaint is unavailable | The complaint is already closed or your role cannot resolve complaints. | Review history. Ask authorized HomeBiogas resolution staff if closure is required. |
| Reopen Complaint is unavailable | The complaint is not closed or your role cannot reopen. | Ask a Complaint Manager to review it. |
| Complete Legacy Case Details is unavailable | The complaint is not marked Needs More Information or your role cannot complete it. | Refresh and confirm status; otherwise ask an Officer or Manager. |
| The app says the complaint is already resolved | A retry or another staff action closed it first. | Refresh and review Resolution History instead of resubmitting. |

### Google Sheet synchronization problems

| What you see | Meaning | Remedy |
| --- | --- | --- |
| Sheet Sync: Pending | The complaint is safe in the Mini App, but publication has not completed. | Wait briefly and refresh. Do not create another complaint. |
| Sheet Sync: Failed | The saved complaint could not be published on the latest attempt. | Record the complaint reference and ask Manager/IT to retry publication and check Sheet access/configuration. |
| Sheet Sync: Not enabled | Publication is disabled for this complaint group. | Continue using the Mini App. Ask IT whether this is intentional. |
| The Sheet row looks older than the Mini App | Publication is pending/failed or someone manually changed the Sheet. | Trust the Mini App's complaint detail and audit history; ask Manager/IT to reconcile the projection. |
| The complaint is in the Mini App but not the Sheet | The main save succeeded while Google publication failed or is delayed. | Do not re-enter it. Escalate the existing complaint reference for synchronization retry. |

### Download problems

| What you see | Likely reason | Remedy |
| --- | --- | --- |
| Download cancelled | The Telegram confirmation was declined. | Tap **Download Again** and accept the prompt. |
| Download link is no longer available or expired | The protected link is intentionally short-lived. | Return to Data Overview and create a fresh download. |
| Telegram cannot open the download | Telegram or the phone browser is outdated or blocked. | Update Telegram, allow downloads, and retry; the app may open the browser as a fallback. |
| Export contains more rows than the filtered table | The governed export intentionally contains all complaint groups. | This is expected and is stated in the confirmation. Apply local workbook filters only after secure download. |

### What to include when escalating to IT

Provide:

- complaint reference, if one exists;
- screen and action attempted;
- exact error message;
- error Reference, if displayed;
- date and time;
- whether retry/refresh changed the result;
- Sheet Sync label, where relevant; and
- a privacy-safe screenshot.

Do not send customer evidence or a full complaints workbook unless IT requests
it through an approved channel.

---

## 16. Quick reference

### Daily user checklist

1. Open Complaints from the approved Telegram launcher.
2. Check the **Open** count and work the oldest relevant complaints.
3. Search before creating a possible duplicate.
4. Capture complete customer, location, and complaint information.
5. Use meaningful descriptions and resolution notes.
6. Confirm the complaint reference after submission.
7. Check Sheet Sync, but never recreate a saved complaint solely because the
   Sheet is delayed.
8. Reopen the same incident if the resolution did not hold.
9. Protect customer information and evidence.

### Status guide

| Status | Meaning |
| --- | --- |
| Open | The complaint requires action. |
| Needs More Information | A historical complaint is missing required identifiers or category. |
| Reopened | A previously closed complaint requires further work. |
| Closed | Authorized resolution staff recorded the outcome. |

### Key distinction

```text
Mini App = authoritative complaint record and audit history
Google Sheet = synchronized operational register
Google Drive = controlled attachment storage
Telegram = authenticated way staff open and use the Mini App
```

---

## 17. Screenshot checklist

Use the following file names in the final publication package so image links
remain predictable. Keep screenshots outside Git by default. Replace each
matching screenshot note with an image only in the distributed manual copy.

A screenshot may be committed to this repository only when it is fully
synthetic, reviewed, hash-pinned, and allowlisted under the repository data and
artifact policy. Never commit a screenshot copied from a live complaint group,
Google Sheet, evidence file, or report.

| No. | Suggested file name | Screen/content |
| --- | --- | --- |
| 1 | `01-opening-header.png` | App header and signed-in role |
| 2 | `02-complaint-queue.png` | Queue, tabs, counts, search, pagination |
| 3 | `03-new-complaint-form.png` | Full new complaint form |
| 4 | `04-category-location.png` | Category suggestion and GPS success |
| 5 | `05-complaint-detail.png` | Full complaint detail |
| 6 | `06-complete-details.png` | Needs More Information correction |
| 7 | `07-resolve-complaint.png` | Resolution form |
| 8 | `08-reopen-complaint.png` | Reopen form and prior resolution |
| 9 | `09-camera.png` and `09-camera-selected-files.png` | Camera and pending evidence viewer |
| 10 | `10-secure-evidence.png` | Saved evidence preview |
| 11 | `11-data-overview.png` | Metrics and charts |
| 12 | `12-report-filters.png` | Report filter controls |
| 13 | `13-report-table.png` | Report table, table size, scrolling, pages |
| 14 | `14-export-download.png` | Export confirmation and ready state |
| 15 | `15-google-register.png` | Manual Google Sheet overview |
| 16 | `16-synchronized-row.png` | Manual synchronized Sheet row |
| 17 | `17-resolved-reopened-sheet.png` | Manual resolved/reopened Sheet rows |

Before publishing the manual, check every screenshot at ordinary phone size,
remove or replace all real customer information, and ensure the visible labels
match the current production release.
