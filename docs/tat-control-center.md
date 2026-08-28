# TAT Control Center manual

## Purpose

The TAT Control Center replaces the need to remember a sequence of unrelated Django Admin models. It is a guided, full-width workspace over the same governed models; it does not create a second configuration database.

Open **Django Admin -> TAT access & responsibilities -> Guided setup**. Only an active Django Superuser can open or mutate this workspace. Business access remains governed through `AccessGrant` and its maker-checker workflow.

## Setup walkthrough

1. **Group and branches**
   - Select the Telegram workflow group.
   - Confirm the governed branch list and notification mode.
   - New TAT groups default to Django-only register mode. Existing groups retain Sheet projection after migration.
2. **Products**
   - Confirm every TAT product has a global `ProductVersion` and `ProductTatConfiguration`.
   - Published product versions are immutable.
3. **Visual stages**
   - Open **Design stages** for a product.
   - Use **Add stage**, arrow controls, and **Remove** to define the ordered flow.
   - Every stage needs a stable key, label, responsible role, unique positive Sheet column, and control type.
   - A dropdown also needs one option per line.
   - Saving a published version creates or reuses its editable successor. Existing cases keep their frozen stage snapshot.
4. **Access coverage**
   - Grant staff TAT access through the existing maker-checker AccessGrant process.
   - A responsibility assignment routes work; it never grants permission.
5. **Responsibilities**
   - Configure primary owners and ranked backups per branch/product/role or stage.
   - Changing a roster does not silently move open work. Use **Reroute** on an open register row when movement is intended.
6. **Alerts and SLA**
   - Select `group`, `shadow`, or `hybrid` notification mode and configure stage/total targets.
   - Private delivery still requires a matching access scope and connected Telegram identity.
7. **Register projection**
   - Use the built-in register as the canonical operational view.
   - Sheet projection can be disabled only after at least seven days of parallel evidence, three healthy parity audits, a healthy latest audit, no pending/failed Sheet operation, and no legacy-bound case.
8. **Review**
   - Resolve every `unresolved` case by selecting the reviewed immutable product version and recording a reason.
   - `legacy_assumed` cases remain operational but block bulk migration and Sheet cutover until resolved.

## Built-in register

The register supports case-reference, branch, product, status, stage, and owner filtering with server-side pagination. The stage board uses the same filtered dataset.

The XLSX export is deliberately narrower than the screen and database. It includes only:

- case reference;
- branch;
- product and exact version;
- stage and responsible role;
- current owner and status;
- SLA timestamps/minutes; and
- created/updated timestamps.

It never exports applicant/customer names, national IDs, phone numbers, Telegram IDs, remarks, evidence, or arbitrary free text. Every export is written to the compliance audit ledger with actor, request ID, filters, field allowlist, and row count—not the exported rows.

## Explicit task rerouting

Open a pending case in the register and choose **Reroute**. Supply a meaningful reason. The service locks the case and pending task, revalidates that no stage completion won the race, increments `routing_generation`, revokes removed recipients' locators, and creates delivery state for the current approved roster. The append-only reroute event records before/after recipient IDs and generations without customer data.

If stage completion commits first, rerouting stops with a calm stale-state message. If rerouting commits first, old locator tokens stay invalid even if an already-running Telegram delivery returns later.

## Legacy configuration resolution

- `versioned`: exact `ProductVersion` and TAT stage bytes are frozen on the case.
- `legacy_assumed`: the case predates exact binding and can continue under the compatibility adapter, but is visibly flagged.
- `unresolved`: no safe mapping exists; the case is read-only.

Choose **Resolve version** in the register. The selected product must match the case, and every stage already present in case history must exist in the selected configuration. The reason and before/after binding are append-only audit evidence.

## Visual verification checklist

Run the local server, sign in as an active Superuser, and test at desktop width (1440px), tablet width (900px), and phone width (390px):

1. Open `/admin/core/tatresponsibilityassignment/` and confirm **Guided setup** and **Built-in register** are visible.
2. Confirm the workspace uses the available horizontal space without hiding the Admin sidebar.
3. Change the selected group/branch/product and verify cards update without squeezed controls.
4. Open a product stage designer; add, reorder, and remove a stage. Submit without a reason and confirm it is blocked. Save with a reason and confirm a published source opens an editable successor.
5. Open the register; test 25/50/100 row sizes and Previous/Next navigation.
6. Filter the register, export XLSX, and verify excluded PII fields are absent.
7. Open a pending task, reroute it, then confirm an old locator cannot reopen the task.
8. Confirm unresolved/assumed rows show **Resolve version** rather than ordinary maintenance actions.
9. Confirm Sheet cutover remains disabled while any evidence blocker is listed.

## Developer and maintenance notes

- Apply migration `0139_guided_tat_control_center` before opening the workspace.
- `TatTrackerCase.tat_configuration_snapshot` is immutable-by-use: normal case processing reads it through `product_for_case()` and must never consult the current active product version for an existing case.
- All task inbox/delivery queries must match recipient and task `routing_generation`.
- Do not issue a new locator without revalidating the generation after the external Telegram request returns.
- `GroupSheetConfiguration.tat_sheet_projection_enabled=False` means local TAT writes succeed without calling Google Sheets. Do not restore a row-number requirement on this path.
- Run focused checks after changes:

  ```powershell
  $env:DJANGO_SECRET_KEY='local-test-only-long-random-value'
  $env:DEBUG='True'
  .venv\Scripts\python.exe manage.py makemigrations --check --dry-run
  .venv\Scripts\python.exe manage.py check
  .venv\Scripts\python.exe manage.py test core.tests_tat_tracker core.tests_tat_notifications --keepdb --noinput
  ```

- Do not enable or disable production Sheet projection from the shell. Use the governed workspace so the cutover evidence and reason are retained.

