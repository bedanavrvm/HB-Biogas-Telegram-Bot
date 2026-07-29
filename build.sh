#!/bin/bash
# Build script for Render deployment
# Installs dependencies and collects static files

set -e  # Exit on any error

echo "Installing dependencies..."
# WeasyPrint renders the access-control evidence PDF. Render's Debian image
# normally supplies these libraries, but install them explicitly so a clean
# deploy fails neither silently nor only when an auditor requests a report.
if command -v apt-get >/dev/null 2>&1; then
  apt-get update -qq
  apt-get install -y -qq libcairo2 libglib2.0-0 libharfbuzz0b libpango-1.0-0 libgdk-pixbuf-2.0-0 libffi-dev shared-mime-info
fi
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
