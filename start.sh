#!/bin/bash
# Start script for Render deployment
# Runs migrations, creates superuser, then starts the Django application

set -e

echo "Running database migrations..."
python manage.py migrate --noinput

echo "Creating superuser if environment variables are set..."
python manage.py createsuperuser_env

echo "Starting Django application..."
exec gunicorn config.wsgi:application --log-file -