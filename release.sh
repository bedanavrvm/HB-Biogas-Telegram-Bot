#!/bin/bash
# Explicit Render pre-deploy command.  This command is intentionally separate
# from start.sh so a restart cannot unexpectedly change database state or call
# Telegram.  Configure it only after database backups are enabled.

set -euo pipefail

echo "Checking production configuration..."
# Warnings (for example, optional Sentry monitoring) remain visible in the
# deploy log but must not block migrations. The management command still
# supports --strict for an explicit, fail-on-warning audit when needed.
python manage.py check_production_readiness

echo "Applying reviewed migrations..."
python manage.py migrate --noinput

echo "Creating configured superuser when it does not already exist..."
python manage.py createsuperuser_env

echo "Release preparation completed."
