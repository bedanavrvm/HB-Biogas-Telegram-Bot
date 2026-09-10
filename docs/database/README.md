# Database Governance

The generated catalogue makes the legacy single-app schema understandable without renaming production tables. `catalog.md` and `catalog.json` identify each physical table, Django model, bounded domain, purpose, lifecycle, retention, parents, children, cross-domain relationships, direct ORM writers, and other code references. `overview.mmd` and the domain `.mmd` files are Mermaid ER sources regenerated from the model graph.

## Standing rules

- New business models belong to the Django app that owns their bounded domain. During legacy `core` decomposition, any exception uses an explicit `<domain>_<entity>_<role>` table name.
- Use `_event`, `_history`, `_state`, `_config`, `_assignment`, `_link`, `_batch`, `_item`, `_artifact`, `_issue`, `_snapshot`, and `_metric` consistently when those roles apply.
- Every new model declares purpose, domain, classification, source-of-truth status, lifecycle, retention, `Meta.db_table_comment`, and a `db_comment` for every column.
- Every relationship has a deliberate `on_delete` policy and intentional reverse name. Parent, child, and cross-domain edges are generated from actual Django relations.
- Every explicit index has a stable name and a catalogue justification. Review production `pg_stat_user_indexes` over a representative observation period before deleting merely unused indexes.
- Event, history, snapshot, diagnostic, notification, and job tables must define retention before release. Permanent retention is an explicit policy, not an omitted policy.
- All schema and comment changes go through checked-in Django migrations. Never use a production GUI to run ad-hoc `ALTER TABLE` or `COMMENT ON` changes.
- Generate and commit the catalogue whenever models change. CI runs `python manage.py generate_database_catalog --check`, making every merged ERD current rather than relying on a calendar reminder.
- Squash only old, settled migration ranges in a dedicated maintenance change after every deployed environment has crossed the replaced range.
- Verify provider backup retention and perform a documented restore drill before table moves, migration squashes, or destructive cleanup.

## Commands

```bash
python manage.py generate_database_catalog
python manage.py generate_database_catalog --check
python manage.py generate_database_catalog --live --output-dir <private-directory>
```

On PostgreSQL, query `database_catalog` in DataGrip or another read-only database client for live estimates and storage. Estimated rows come from PostgreSQL planner statistics and are not exact counts.

PostgreSQL-schema moves (`origination.*`, `tat.*`, and similar) and existing physical-table renames remain deferred. Each should happen only alongside an otherwise necessary domain migration, with compatibility and restore evidence.
