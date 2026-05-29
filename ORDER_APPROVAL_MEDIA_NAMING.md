# Order Approval Media Naming and Drive Structure

This document defines how the order approval workflow stores uploaded ID photos, LAF documents, and other files in Google Drive.

## Drive Directory Structure

Media is stored under the folder configured by:

```text
GOOGLE_DRIVE_MEDIA_FOLDER_ID=<shared-drive-folder-id>
```

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

## JBL Naming Policy Compliance

This follows `JBL_File_Naming_Policy_v1.0.docx` for:

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
