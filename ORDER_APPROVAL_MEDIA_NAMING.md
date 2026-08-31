# Order Approval Media Naming and Drive Structure

This document defines how the order approval workflow stores uploaded ID photos, LAF documents, and other files in Google Drive.

## Drive Directory Structure

Media is stored under the folder configured by:

```text
GOOGLE_DRIVE_MEDIA_FOLDER_ID=<shared-drive-folder-id>
```

Workbook templates use a separate replacement-only branch:

```text
Order Approval Media/
└── Templates/
    ├── Requisition/
    │   └── <template filename>.xlsx
    └── Payment Documents/
        └── <template filename>.xlsx
```

Template uploads are not append-only. Within each category, an upload with
the same filename updates the newest existing Drive file, keeps its Drive ID
stable, and trashes older same-name duplicates. The active Django template
record is the version used for generation; its `drive_uploaded_at` timestamp
identifies the latest upload and the Django Admin marks it `CURRENT / USED`.

The bot creates this structure below that folder. The first child folder is
the Telegram group name from Django admin `display_name`, unless the workflow
sets `media_root_folder`.

```text
Order Approval Media/
+-- <Telegram group name or media_root_folder>/
    +-- 2026/
        +-- May/
            +-- ID_113650221/
                +-- 2026-05-09 KYC ID-113650221 01.jpg
                +-- 2026-05-09 KYC ID-113650221 02.jpg
                +-- 2026-05-09 LAF Biogas ID-113650221 01.pdf
                +-- 2026-05-09 LAF Biogas ID-113650221 02.pdf
                +-- 2026-05-09 FILE Biogas ID-113650221 01.pdf
```

Directory rules:

- `<Telegram group name or media_root_folder>` separates files by workflow/group.
- `2026` is the upload year.
- `May` is the upload month in words.
- `ID_113650221` is the customer ID folder. All uploads for that ID go into the same folder.
- Files are not split into separate subfolders by upload slot. The filename identifies whether the file is KYC, LAF, or general file evidence.

## Filename Pattern

Order approval media uses a date-first pattern:

```text
YYYY-MM-DD TYPE Context ID-<ID_NUMBER> NN.ext
```

Examples:

```text
2026-05-09 KYC ID-113650221 01.jpg
2026-05-09 KYC ID-113650221 02.jpg
2026-05-09 LAF Biogas ID-113650221 01.pdf
2026-05-09 FILE Biogas ID-113650221 01.pdf
```

Element meaning:

- `YYYY-MM-DD`: upload/business date in ISO format. This is first so files sort chronologically inside the ID folder.
- `TYPE`: document category.
- `Context`: product or process context where applicable.
- `ID-<ID_NUMBER>`: the stable business reference requested for this workflow.
- `NN`: two-digit sequence for that file type under the same ID.
- `.ext`: lowercase file extension based on the original upload or MIME type.

## Upload Slot Mapping

| Web form slot | Filename type | Example |
| --- | --- | --- |
| ID photos | `KYC` | `2026-05-09 KYC ID-113650221 01.jpg` |
| LAF document | `LAF Biogas` | `2026-05-09 LAF Biogas ID-113650221 01.pdf` |
| Other files | `FILE Biogas` | `2026-05-09 FILE Biogas ID-113650221 01.pdf` |
| Telegram photo fallback | `KYC` | `2026-05-09 KYC ID-113650221 01.jpg` |
| Telegram document fallback | `FILE Biogas` | `2026-05-09 FILE Biogas ID-113650221 01.pdf` |

## Portal JBL Visit Evidence

JBL visit evidence is a separate Portal workflow. New uploads use one client
National-ID folder within the relevant month. The signed LAF document and JBL
visit photo(s) are therefore kept together rather than being split into
folders by media category.

```text
Order Approval Media/
+-- Jawabu/
    +-- JBL Visits/
        +-- 2026/
            +-- 07-July/
                +-- ID_<national ID>/
                    +-- 2026-07-31 LAF JBL Visit ID-<national ID> 01.pdf
                    +-- 2026-07-31 PHOTO JBL Visit ID-<national ID> 01.jpeg
```

Rules specific to this workflow:

- The National ID is the controlled client reference approved for the
  permissioned Mini App/Shared Drive. Customer name, telephone number, and the
  internal enum must never appear in the Drive path or filename.
- `LAF` and `JBL_VISIT_PHOTO` remain the canonical stored categories for
  querying and audit, but their human-facing Drive filenames are `LAF` and
  `PHOTO` respectively.
- The sequence is per client National ID and evidence type across repeat-unit
  cases: a second visit photo is `... PHOTO JBL Visit ID-<national ID> 02.jpeg`.
- Existing Drive objects are audit evidence. This policy applies only to
  future uploads; prior files are neither renamed nor moved without a separate
  approved migration and Drive-side reconciliation.

## JBL Naming Policy Compliance

The previously reviewed JBL naming-policy requirements are incorporated here
directly; the operational DOCX is intentionally not stored in Git. They require:

- ISO dates: `YYYY-MM-DD`.
- Clear type prefixes: `KYC`, `LAF`, `FILE`.
- Business context: `Biogas` where applicable.
- Stable reference: `ID-<ID_NUMBER>` for this workflow.
- Safe characters only.
- Lowercase file extensions.
- No phone numbers or customer names in filenames.
- No `SIGNED` marker. Staff asked to remove this marker from bot-generated names.

The only deliberate exception is element order. The policy's general pattern is:

```text
TYPE Context Reference YYYY-MM-DD Status.ext
```

For this workflow, the approved bot pattern is date-first:

```text
YYYY-MM-DD TYPE Context Reference NN.ext
```

Reason: within each `ID_<ID_NUMBER>` folder, staff need chronological sorting before document type grouping.

## Multi-File and Duplicate Behavior

- Each upload slot accepts multiple files.
- The bot stores all files for the same ID in the same `ID_<ID_NUMBER>` folder.
- The sequence number is per file type and ID. For example, two ID photos become `KYC ... 01.jpg` and `KYC ... 02.jpg`.
- The bot does not use `p1`, `p2` in filenames because it cannot reliably know whether two uploads are pages of the same document or separate documents.
- Re-uploading the exact same web file, with the same ID, original filename, size, and content hash, reuses the existing Drive upload instead of creating another duplicate file.
- A different file with the same original filename is treated as a new upload and gets the next sequence number.

## Generated Workbook Versioning

Generated operational workbooks are immutable Drive artifacts. Re-generating
an order or payment never reuses the same filename:

```text
JBL_Requisition_Form_<order>_v1.xlsx
JBL_Requisition_Form_<order>_preview_v1.xlsx
HB_Payment_<payment>_<order>_preview_v1.xlsx
HB_Payment_<payment>_<order>_final_v1.xlsx
```

The version increases for every new generation, including retries. The
`RequisitionBatch` row points to the latest order/preview versions, while
`PaymentDocument` retains each preview, failed upload, and final artifact for
audit/history. The portal History screen and Django Admin expose the version
and filename so the latest artifact is unambiguous.
