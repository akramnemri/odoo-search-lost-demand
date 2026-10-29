#!/bin/bash
# Writes $ODOO_RC from the committed template and the container environment, then hands over to the
# official entrypoint. Odoo has no command-line option for the master password (admin_passwd), and
# secrets must never live in the repository or the image (docs/ai/01_ARCHITECTURE.md §12).
set -euo pipefail

: "${ODOO_ADMIN_PASSWD:?}" "${ODOO_DB_NAME:?}" "${ODOO_RC:?}"

python3 - /etc/odoo/odoo.conf.template "$ODOO_RC" <<'PYTHON'
import os
import string
import sys

template_path, target_path = sys.argv[1:3]
with open(template_path, encoding="utf-8") as template:
    # substitute() raises on a missing variable instead of writing an incomplete configuration.
    text = string.Template(template.read()).substitute(os.environ)
with open(target_path, "w", encoding="utf-8") as target:
    target.write(text)
os.chmod(target_path, 0o600)
PYTHON

exec /entrypoint.sh "$@"
