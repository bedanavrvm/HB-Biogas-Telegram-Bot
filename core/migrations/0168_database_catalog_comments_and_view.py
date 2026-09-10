from django.db import migrations


VIEW_SQL = r"""
CREATE OR REPLACE VIEW database_catalog AS
WITH tables AS (
    SELECT c.oid, c.relname AS table_name, c.reltuples::bigint AS estimated_rows,
           pg_total_relation_size(c.oid) AS storage_bytes,
           obj_description(c.oid, 'pg_class') AS table_description
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = current_schema() AND c.relkind = 'r' AND c.relname ~ '^core_'
), parents AS (
    SELECT con.conrelid AS table_oid,
           array_agg(DISTINCT parent.relname ORDER BY parent.relname) AS parent_tables,
           count(*) AS foreign_key_count
    FROM pg_constraint con
    JOIN pg_class parent ON parent.oid = con.confrelid
    WHERE con.contype = 'f'
    GROUP BY con.conrelid
), children AS (
    SELECT con.confrelid AS table_oid,
           array_agg(DISTINCT child.relname ORDER BY child.relname) AS child_tables
    FROM pg_constraint con
    JOIN pg_class child ON child.oid = con.conrelid
    WHERE con.contype = 'f'
    GROUP BY con.confrelid
), indexes AS (
    SELECT indrelid AS table_oid, count(*) AS index_count
    FROM pg_index GROUP BY indrelid
)
SELECT t.table_name,
       substring(t.table_description FROM 'Domain: ([^.]+)') AS domain,
       t.table_description,
       substring(t.table_description FROM 'Lifecycle: ([^.]+)') AS lifecycle,
       t.estimated_rows,
       t.storage_bytes,
       pg_size_pretty(t.storage_bytes) AS storage,
       COALESCE(p.parent_tables, ARRAY[]::name[]) AS parent_tables,
       COALESCE(ch.child_tables, ARRAY[]::name[]) AS child_tables,
       COALESCE(p.foreign_key_count, 0) AS foreign_key_count,
       COALESCE(i.index_count, 0) AS index_count
FROM tables t
LEFT JOIN parents p ON p.table_oid = t.oid
LEFT JOIN children ch ON ch.table_oid = t.oid
LEFT JOIN indexes i ON i.table_oid = t.oid
ORDER BY domain, t.table_name
"""


def add_catalog(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    # Import current descriptive metadata only; introspection prevents this
    # historical migration from addressing tables created by later migrations.
    from core.services.database_catalog import column_comment, database_catalog, table_comment

    quote = schema_editor.quote_name
    existing = set(schema_editor.connection.introspection.table_names())
    entries = {item['table']: item for item in database_catalog(include_usage=True)}
    with schema_editor.connection.cursor() as cursor:
        for model in apps.get_app_config('core').get_models():
            table = model._meta.db_table
            if table not in existing or table not in entries:
                continue
            cursor.execute(f'COMMENT ON TABLE {quote(table)} IS %s', [table_comment(entries[table])])
            for field in model._meta.concrete_fields:
                cursor.execute(
                    f'COMMENT ON COLUMN {quote(table)}.{quote(field.column)} IS %s',
                    [column_comment(field)],
                )
        cursor.execute(VIEW_SQL)
        cursor.execute(
            "COMMENT ON VIEW database_catalog IS %s",
            ['Read-only live PostgreSQL catalogue for application tables, relationships, row estimates, storage and indexes.'],
        )


def remove_catalog(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    quote = schema_editor.quote_name
    existing = set(schema_editor.connection.introspection.table_names())
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('DROP VIEW IF EXISTS database_catalog')
        for model in apps.get_app_config('core').get_models():
            table = model._meta.db_table
            if table not in existing:
                continue
            for field in model._meta.concrete_fields:
                cursor.execute(f'COMMENT ON COLUMN {quote(table)}.{quote(field.column)} IS NULL')
            cursor.execute(f'COMMENT ON TABLE {quote(table)} IS NULL')


class Migration(migrations.Migration):
    dependencies = [('core', '0167_remove_exact_duplicate_indexes')]
    operations = [migrations.RunPython(add_catalog, remove_catalog)]
