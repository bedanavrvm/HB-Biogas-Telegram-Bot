from django.db import migrations


# Human-observable checks only. A result is recorded in a scoped release cycle,
# not in this seed or in an editable spreadsheet.
CHECKS = {
    'tat_tracker': [
        ('TAT-01', 'Launch and tasks', 'Open a private task from Telegram, refresh its case, and use Back.', 'The exact case opens; refresh keeps access and context; Back returns to the task or previous screen.'),
        ('TAT-02', 'Work queue', 'Compare Ready for my role, All cases, search, and queue filters on a phone.', 'The actionable queue is obvious, active filters are visible, and tabs fill available width.'),
        ('TAT-03', 'Case detail', 'Open a case and inspect stage order, current owner, target, and history.', 'Stages follow the loan cycle; the next action and elapsed/target meaning are understandable.'),
        ('TAT-04', 'Stage action', 'Open a stage outcome form, add remarks, then cancel and reopen it.', 'The form exposes only relevant fields, preserves intended input, and explains the action before submission.'),
        ('TAT-05', 'Correction', 'Inspect correction of a completed stage and an earlier proposed timestamp.', 'The prior event and correction reason remain clear; invalid chronology is explained before a save.'),
        ('TAT-06', 'Reports', 'Switch report insights, chart/list presentation, and filters on a narrow device.', 'Chart titles, stage labels, selected filters, and empty states remain readable without horizontal overflow.'),
        ('TAT-07', 'Recognition', 'Open Monthly recognition with zero, unranked, and ranked examples.', 'Personal progress and standings are compact and plain-language; staff do not see audit jargon.'),
        ('TAT-08', 'Notifications', 'Open and dismiss the bell, then trigger a success and a failure.', 'The bell matches Portal behavior and one pop-down toast communicates each outcome.'),
        ('TAT-09', 'Optional appraisal', 'Open case detail with credit-assessment Gmail disabled, then enabled in a test environment.', 'The appraisal section is absent when disabled; when enabled, evidence and review follow TAT stage order.'),
    ],
    'complaints': [
        ('CMP-QA-01', 'Queue', 'Switch Open, Closed, and All, then search by complaint reference on a phone.', 'Counts and cards agree; the consecutive complaint reference is easy to find.'),
        ('CMP-QA-02', 'Create', 'Open New Complaint and inspect identity, detail, type, and evidence controls.', 'The form is short, labels are plain, and the selected evidence remains visible before submission.'),
        ('CMP-QA-03', 'Type suggestion', 'Enter an ambiguous natural-language complaint and inspect the suggested type.', 'The suggestion is optional and understandable; Other is not selected merely because a keyword appears.'),
        ('CMP-QA-04', 'Voice input', 'Record, stop, review, and discard voice input for complaint detail.', 'Controls align with the field; text is editable and never submitted without the user seeing it.'),
        ('CMP-QA-05', 'Case inspection', 'Open a complaint, preview two attachments, and return to the queue.', 'Preview and Back/Close form a predictable route; history and action context remain intact.'),
        ('CMP-QA-06', 'Resolution', 'Open Resolve, add a voice or typed note and evidence, then inspect the result.', 'The note and evidence are clearly tied to the action; the case moves to Closed with a readable history entry.'),
        ('CMP-QA-07', 'Reopening', 'Reopen a closed complaint with a reason and inspect the case afterward.', 'The reason is clear, prior resolution remains visible, and the case returns to Open.'),
        ('CMP-QA-08', 'Management overview', 'Open Data Overview, change chart/table filters, and confirm the export dialog.', 'Charts and grid remain legible; the dialog names the download without irrelevant group text.'),
        ('CMP-QA-09', 'Legacy details', 'Open an older Needs details case where one is available.', 'The missing intake fields are explained and editable without implying the case is a new complaint.'),
    ],
    'spin': [
        ('SPIN-QA-01', 'Request form', 'Open New Request and inspect customer, loan, document, and summary sections.', 'The request path is clear on a phone and the summary reflects visible inputs.'),
        ('SPIN-QA-02', 'Draft recovery', 'Enter part of a request, leave the app, return, and choose to restore or clear it.', 'The choice is explicit; text returns correctly and files are requested again if necessary.'),
        ('SPIN-QA-03', 'Request dashboard', 'Switch All, Awaiting review, Batch candidates, and Completed; search and filter.', 'Counts, cards, status wording, and selected filters remain coherent.'),
        ('SPIN-QA-04', 'Review', 'Open a request needing review and inspect customer and branch corrections.', 'The reason for review and changed fields are obvious; Cancel returns to the same dashboard context.'),
        ('SPIN-QA-05', 'Analyst completion', 'Open Submit Reports and inspect attachment and outcome controls.', 'Required reports and the effect of submission are clear; the modal fits a narrow phone.'),
        ('SPIN-QA-06', 'Settings and mode', 'Open personal settings and inspect Pilot or Production labeling if configured.', 'Settings show only personal controls; test-data mode is unmistakable where relevant.'),
    ],
    'origination': [
        ('ORI-QA-01', 'Applications', 'Open the application list and create a new application for an available product.', 'The product choice and next step are clear; no unrelated product fields appear.'),
        ('ORI-QA-02', 'Conditional form', 'Work through the product-specific form with optional and repeated sections.', 'Only relevant fields appear, repeatable rows are usable, and progress is clear on a phone.'),
        ('ORI-QA-03', 'Draft recovery', 'Enter an unfinished application, background the app, then return.', 'The draft recovers without silently overwriting newer server data or losing typed work.'),
        ('ORI-QA-04', 'Documents', 'Choose the Main LAF and supporting documents, then open packet preview.', 'Selections are understandable; pages, navigation, and zoom work before signing.'),
        ('ORI-QA-05', 'Maker-checker', 'Inspect a correction request and reopen the affected draft.', 'The exact field or document needing correction is evident; unrelated completed work remains intact.'),
        ('ORI-QA-06', 'Signing', 'In an approved test environment, inspect signer instructions and the resulting packet.', 'Consent, role, signature placement, and final state are clear; test signing cannot appear legally final.'),
        ('ORI-QA-07', 'Mobile navigation', 'Move list to draft to preview to review dialog and back on a narrow phone.', 'Close/Back returns to the prior context and keyboard or overlays do not hide final actions.'),
    ],
    'fca_review': [
        ('FCA-QA-01', 'Upload review', 'Open a current FCA upload review link and inspect extracted Section A rows.', 'Source rows, status, and review decisions are readable without losing the row identity.'),
        ('FCA-QA-02', 'Row selection', 'Select some valid rows, leave another needing review, and inspect the commit summary.', 'Selected and held rows are unmistakable; the action states exactly what will commit.'),
        ('FCA-QA-03', 'Unavailable link', 'Open an expired or missing FCA review link.', 'A plain unavailable message and safe next step appear rather than a blank page.'),
    ],
    'farmers_review': [
        ('FARM-QA-01', 'Upload review', 'Open a current Farmers or System Export review link and inspect extracted rows.', 'The source kind, match state, name, ID, and row action remain distinguishable.'),
        ('FARM-QA-02', 'Search and selection', 'Search rows, show Needs review only, and select a subset for commit.', 'Counts and selection remain coherent; unselected rows are visibly held.'),
        ('FARM-QA-03', 'Unavailable link', 'Open an expired or missing upload review link.', 'A clear unavailable message appears without exposing old upload data.'),
    ],
    'order_approval': [
        ('ORDER-QA-01', 'Customer lookup', 'Open the order-approval form, load an existing customer, and inspect the populated sections.', 'Loaded values, editable fields, and the source of information are understandable.'),
        ('ORDER-QA-02', 'Draft recovery', 'Enter an unfinished form, go offline briefly, then restore it.', 'Text survives as promised; attachments are explicitly reselected before submission.'),
        ('ORDER-QA-03', 'Section layout', 'Expand and collapse Customer, Visit, and later form sections on a narrow phone.', 'Field order is logical; controls and save actions remain reachable above the keyboard.'),
        ('ORDER-QA-04', 'Review and archive', 'Inspect the review state and an archived/unavailable order-approval link.', 'The current action is unambiguous; archived links explain where to continue instead of showing a broken form.'),
    ],
}


def seed(apps, schema_editor):
    TestCase = apps.get_model('qa_tracker', 'TestCase')
    for app, checks in CHECKS.items():
        for identifier, journey, steps, expected in checks:
            TestCase.objects.get_or_create(
                id=identifier,
                defaults={
                    'app': app, 'journey': journey,
                    'description': steps.rstrip('.'), 'steps': steps,
                    'expected': expected, 'priority': 'high', 'active': True,
                    'automation_gap': False,
                },
            )


class Migration(migrations.Migration):
    dependencies = [('qa_tracker', '0005_alter_testcycle_app')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
