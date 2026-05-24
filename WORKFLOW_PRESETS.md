# Workflow Presets

Workflow presets make Telegram group setup simple and consistent.

Admin setup should normally be:

```text
1. Paste Telegram group ID
2. Paste Google Sheet ID
3. Select Workflow Preset
4. Save
```

Avoid editing `GROUP_MAPPING_JSON` or hand-writing workflow JSON unless there is a specific deployment reason.

## Current Presets

### Manual JSON / Complaint Workflow

Use this for the existing complaint/case groups.

This preset does not generate workflow JSON. It preserves the current behavior:

- Bot mention is required in group messages.
- Message goes through the existing complaint/case parser.
- New cases are written to the configured complaint register.
- Case status replies and `/update MSG_ID Status: ...` keep working.
- Existing `sheet_schema`, `workflow`, and `parser_rules` values are preserved.

Use this when configuring:

```text
Complaints Register
Support cases using the current ParsedMessage model
Any group that should keep the existing complaint parser
```

Recommended admin fields:

```text
enabled: checked
group_id: -100...
display_name: Complaints
sheet_id: <complaint-sheet-id>
sheet_name: Complaints Register
workflow_preset: Manual JSON / complaint workflow
```

Leave advanced JSON fields empty unless that group needs a custom sheet schema or custom workflow metadata.

### Order Approval

Use this only for the separate order approval Telegram group.

This preset generates:

```json
{
  "type": "order_approval",
  "match_field": "id_number",
  "search_sheet_names": ["Orders"],
  "create_sheet_name": "Orders",
  "media_field": "media_urls",
  "header_row": 2
}
```

Behavior:

- `/order` opens the Telegram Web App form.
- Structured chat updates still work as a fallback.
- Rows are matched by `ID NUMBER`.
- If no row exists for the ID, a new row is created in `Orders`.
- Only BRO fields and `Media URLs` are updated.
- Photos/documents are uploaded to Google Drive.
- `OrderApprovalUpdate` and `MediaAttachment` audit records are written.

Recommended admin fields:

```text
enabled: checked
group_id: -100...
display_name: Order Approval
sheet_id: <order-approval-sheet-id>
sheet_name: Orders
workflow_preset: Order Approval
order_approval_search_tabs: Orders
order_approval_match_field: ID NUMBER
order_approval_media_field: Media URLs
```

The `Orders` worksheet must already contain:

```text
ID NUMBER
Media URLs
```

Those headers must be on row 2. Row 1 may be a visual title/banner.

The bot does not insert columns into the approval workbook.

## Are Existing Groups OK?

Yes.

Existing complaint groups are OK if they either:

- Have no workflow type, or
- Use the `Manual JSON / complaint workflow` preset, or
- Have older custom workflow JSON without `type: "order_approval"`.

The webhook only switches to the order approval workflow when:

```json
{
  "type": "order_approval"
}
```

All other configured groups continue through the original complaint/case processing path.

## Where Presets Live

Preset definitions live in:

```text
core/services/workflow_presets.py
```

The Django admin form reads from this file. This keeps group setup consistent and makes future workflow additions predictable.

## Adding A New Workflow Preset

For a new group workflow, add one entry to `WORKFLOW_PRESETS`.

Example shape:

```python
WORKFLOW_PRESETS = {
    "installations": {
        "label": "Installations",
        "description": "Installation scheduling and media workflow.",
        "sheet_name": "Installations",
        "workflow": {
            "type": "installations",
            "match_field": "customer_id"
        },
        "sheet_schema": {},
        "parser_rules": {},
        "admin_fields": {}
    }
}
```

Then implement the workflow service and route it from the webhook based on:

```python
group_config.workflow.get("type")
```

Keep this rule: admins select presets; developers define presets.

## Operational Rules

- Use Django admin as the source of truth for group setup.
- Keep `GROUP_MAPPING_JSON` only for bootstrap or emergency deployments.
- Do not put secrets in preset JSON.
- Do not make presets auto-create sheet columns.
- Prefer header-based sheet writes over fixed column positions.
- Add tests for every new preset.
