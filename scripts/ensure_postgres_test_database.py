"""Create the local PostgreSQL connection database for Django test runs.

This only creates the guarded, local database named by TEST_DATABASE_URL. It
never drops or alters an existing database; Django owns its separate temporary
test database (normally ``test_<name>``).
"""
from __future__ import annotations

import os
import sys
from urllib.parse import urlsplit

import psycopg
from psycopg import errors, sql
from psycopg.conninfo import conninfo_to_dict


def main() -> int:
    database_url = str(os.environ.get('TEST_DATABASE_URL') or '').strip()
    if not database_url:
        print('TEST_DATABASE_URL is required.', file=sys.stderr)
        return 2

    parsed = urlsplit(database_url)
    database_name = parsed.path.lstrip('/')
    if parsed.scheme not in {'postgres', 'postgresql'}:
        print('TEST_DATABASE_URL must use PostgreSQL.', file=sys.stderr)
        return 2
    if parsed.hostname not in {'127.0.0.1', 'localhost', '::1'}:
        print('Refusing to bootstrap a non-local PostgreSQL database.', file=sys.stderr)
        return 2
    if not database_name or 'test' not in database_name.casefold():
        print('The local PostgreSQL database name must contain "test".', file=sys.stderr)
        return 2

    connection_parameters = conninfo_to_dict(database_url)
    connection_parameters['dbname'] = 'postgres'
    try:
        with psycopg.connect(**connection_parameters, autocommit=True) as connection:
            exists = connection.execute(
                'SELECT 1 FROM pg_database WHERE datname = %s', (database_name,),
            ).fetchone()
            if exists:
                print(f'Local PostgreSQL test database is ready: {database_name}')
                return 0
            connection.execute(
                sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database_name)),
            )
            print(f'Created local PostgreSQL test database: {database_name}')
            return 0
    except errors.DuplicateDatabase:
        # Another local test runner may have created it between the existence
        # check and CREATE DATABASE. Treat that race as successful setup.
        print(f'Local PostgreSQL test database is ready: {database_name}')
        return 0
    except errors.InsufficientPrivilege:
        print(
            'The local test role needs CREATEDB permission to create the '
            f'connection database {database_name}.',
            file=sys.stderr,
        )
        return 2
    except psycopg.Error as exc:
        print(f'Could not prepare the local PostgreSQL test database: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
