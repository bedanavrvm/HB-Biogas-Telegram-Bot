#!/bin/bash
# Build script for Render deployment
# Installs dependencies, runs migrations, creates superuser, and collects static files

set -e  # Exit on any error

echo "Installing dependencies..."
pip install -r requirements.txt

echo "Running database migrations..."
python manage.py migrate

echo "Creating superuser if environment variables are set..."
python manage.py createsuperuser_env

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Build completed successfully!"