#!/bin/bash
# Build script for Render deployment
# Installs dependencies and collects static files

set -e  # Exit on any error

echo "Installing dependencies..."
pip install -r requirements.txt

echo "Checking Django configuration and migrations..."
python manage.py check
python manage.py makemigrations --check --dry-run
# Schema changes belong in Render's pre-deploy/release command after a
# database backup.  Running migrations during an image build can execute
# against a live database, cannot be rolled back with the image, and caused
# the pending-trigger/index failure seen during deployment.

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Build completed successfully!"
