#!/bin/bash
# Build script for Render deployment
# Installs dependencies and collects static files

set -e  # Exit on any error

echo "Installing dependencies..."
pip install -r requirements.txt

echo "Checking Django configuration and migrations..."
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Build completed successfully!"
