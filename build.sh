#!/bin/bash
# Build script for Render deployment
# Installs dependencies and collects static files

set -e  # Exit on any error

echo "Installing dependencies..."
# Render's native build environment may expose apt but mounts its package-list
# directory read-only. Do not mutate OS packages during an application build;
# the PDF preflight below verifies that the base image can render WeasyPrint.
pip install -r requirements.txt
python -c "from weasyprint import HTML; assert HTML(string='<p>PDF preflight</p>').write_pdf().startswith(b'%PDF')"

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
