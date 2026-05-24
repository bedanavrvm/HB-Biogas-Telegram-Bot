#!/bin/bash
# Start script for Render deployment
# Runs migrations, creates superuser, then starts the Django application

set -e

echo "Running database migrations..."
python manage.py migrate --noinput

echo "Creating superuser if environment variables are set..."
python manage.py createsuperuser_env

echo "Syncing Telegram command autocomplete menu..."
python manage.py sync_telegram_commands || echo "WARNING: Telegram command menu sync failed; app startup will continue."

echo "Starting Django application..."
exec gunicorn config.wsgi:application --log-file -
