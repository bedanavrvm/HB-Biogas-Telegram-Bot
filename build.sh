#!/bin/bash
# Build script for Render deployment
# Installs dependencies and collects static files

set -e  # Exit on any error

echo "Installing dependencies..."
# Render's native build environment may expose apt but mounts its package-list
# directory read-only. Do not mutate OS packages during an application build;
# the PDF preflight below verifies that the base image can render WeasyPrint.
pip install -r requirements.txt
python -m origination.services.signature_appearance
python -c "from weasyprint import HTML; assert HTML(string='<p>PDF preflight</p>').write_pdf().startswith(b'%PDF')"

echo "Building the native staff browser client..."
node -e "if (!process.version.startsWith('v22.')) { throw new Error('Use the pinned Node 22 runtime from .node-version'); }"
npm --prefix browser ci --include=dev
npm --prefix browser run check:dependencies
npm --prefix browser run typecheck
npm --prefix browser run lint
npm --prefix browser run build -- --complaints-operations --production-browser

echo "Checking Django configuration and migrations..."
python manage.py check
python manage.py makemigrations --check --dry-run
# Schema changes belong in Render's pre-deploy/release command after a
# database backup.  Running migrations during an image build can execute
# against a live database, cannot be rolled back with the image, and caused
# the pending-trigger/index failure seen during deployment.

echo "Collecting static files..."
# django-unfold intentionally overrides two stock Django Admin files. The
# first-loaded copy is deterministic because Unfold precedes Django Admin in
# INSTALLED_APPS; suppress that known collectstatic collision at build output.
python manage.py collectstatic --noinput --verbosity 0

echo "Build completed successfully!"
