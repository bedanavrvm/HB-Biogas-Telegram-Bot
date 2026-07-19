#!/bin/bash
# Start script for Render deployment.
#
# Do not run migrations or contact Telegram here: a Render restart must only
# start serving the already-reviewed release.  Run release.sh as Render's
# pre-deploy command after taking a backup and reviewing its output.

set -e

echo "Starting Django application..."
exec gunicorn config.wsgi:application --log-file -
