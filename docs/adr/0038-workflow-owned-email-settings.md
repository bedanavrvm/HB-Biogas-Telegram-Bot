# Workflow-owned email settings

Portal, TAT and Complaints share the Resend delivery engine, but each owns its reports, recipient approvals and IT settings. Workflow ownership is persisted on schedules and approved recipients; a complete current IT grant for that exact workflow and scope is required. Reusing Portal grants across apps was rejected because it would expose unrelated reports.

IT configures recipients and schedules in each Mini App: Portal's Settings screen, TAT's Settings tab, and a header gear opening a scrollable Settings panel in Complaints. Credentials stay server-side. Report adapters reuse each workflow's reporting services; no customer joins or new queue infrastructure are introduced.

Existing configurations migrate to Portal ownership. The new migration is reversible with `python manage.py migrate report_delivery 0002_alter_approvedrecipient_authorized_by_and_more`. Before reversal, pause sending and remove or export TAT/Complaints configurations; otherwise losing the ownership discriminator could misclassify retained records. No production migration or real email is part of this change.
