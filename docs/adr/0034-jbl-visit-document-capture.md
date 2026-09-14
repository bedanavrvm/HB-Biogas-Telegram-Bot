# JBL Visit guided document capture

Date: 2026-09-14

## Context

JBL Visit previously collected unstructured LAF files and visit photos. Staff
need a separately identified two-sided Client ID and an exactly two-page LAF.
Document capture must not change visit permissions or the existing action flow.

## Decision

Use two named image slots per document, with camera/gallery, preview, retake and
remove controls. Collate Client ID onto one PDF page and LAF into two PDF pages
on the server using the existing WeasyPrint dependency. Images are decoded,
orientation-corrected and bounded before rendering; no uploaded HTML, URLs, OCR
or external document service is involved. Store only the completed PDFs as
CLIENT_ID and LAF using existing case-linked, audited MediaAttachment storage.
Supporting photos remain individual JBL_VISIT_PHOTO attachments.

PORTAL_JBL_VISIT_MAX_FILES now limits supporting photos separately from the four
fixed document captures. MEDIA_MAX_FILE_SIZE_MB bounds each source and generated
document; PORTAL_JBL_VISIT_MAX_TOTAL_UPLOAD_MB bounds the complete source request
and resulting storage batch. Both document halves are required if either is
selected. Forwarding additionally requires Client ID, LAF and a supporting photo;
other outcomes may omit these documents. Previously stored attachments are not
rewritten or deleted. Successful stored categories can be reused during retry.

Keep existing portal.jbl_media.write/view permissions and case/branch scope;
this change does not expand the permission matrix. ID remains protected media,
never a public asset. Local captures remain in memory across Case History
inspection, but are not recoverable after closing or reloading the app.

## Consequences

Each submitted document is a complete logical artifact; a failed category leaves
the visit unlogged with explicit evidence-saved/retry information. Stable PDF
content hashes reuse uploads on retries. No schema migration or new dependency
is required. Production requires the existing WeasyPrint native libraries.

## Alternatives considered

Client-only PDF generation adds a frontend dependency and trusts client
collation. Storing unrelated front/back attachments makes completeness and page
order ambiguous. Combining LAF onto one page sacrifices readability.

## Rollback

Revert this change and redeploy the preceding assets/services together. No schema
reversal is needed; stored CLIENT_ID PDFs remain immutable attachments.
