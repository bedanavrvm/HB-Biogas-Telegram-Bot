#!/bin/bash
# Explicit Render pre-deploy command.  This command is intentionally separate
# from start.sh so a restart cannot unexpectedly change database state or call
# Telegram.  Configure it only after database backups are enabled.

set -euo pipefail

# The command verifies all enabled-workflow readiness and immutable backup
# attribution before it is allowed to invoke Django's migrate command.
python manage.py release_production
