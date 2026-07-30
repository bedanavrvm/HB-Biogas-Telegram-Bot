# Technical debt register

Last reviewed: 30-July-2026

This register records deliberate boundaries and shortcuts. It is not a licence
to leave a live risk unowned; update it in the same change that resolves or
introduces an item.

| Priority | Area | Current boundary | Next safe action |
|---|---|---|---|
| High | `core/api/views.py` / `core/api/portal_views.py` | Large legacy HTTP modules still contain orchestration across multiple workflows. | Extract one bounded endpoint family at a time with contract tests; do not combine with policy changes. |
| High | Integration retries | Shared Sheets batch writes, Drive uploads, and launcher publishing use the durable register; other legacy direct API callers do not yet. | Migrate one integration family per release after adding replay/failure tests. |
| Medium | External operations | No Celery/Redis worker or scheduler is enabled. Dead-letter records require explicit operator review/retry. | Propose a separate ADR and operational design before adding a worker. |
| Medium | Type safety | High-risk shared helpers are annotated; broad `mypy` adoption is intentionally deferred. | Add annotations when changing transition, capability, financial, or reliability service functions. |
| Medium | API-view ORM baseline | One legacy direct audit insertion is baselineed. | Move it into its service when altering the JBL media access endpoint. |
