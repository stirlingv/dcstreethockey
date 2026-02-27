#!/usr/bin/env bash
# Exit on error
set -o errexit

# Modify this line as needed for your package manager (pip, poetry, etc.)
pip install -r requirements.txt

# Convert static asset files
python manage.py collectstatic --no-input

# Apply any outstanding database migrations
python manage.py migrate

# Ensure the Quick Cancel Operators group and permission exist.
# If QUICK_CANCEL_USER and QUICK_CANCEL_PASS env vars are set, also create/
# update the user (set them in the Render dashboard, not in this file).
if [ -n "${QUICK_CANCEL_USER:-}" ] && [ -n "${QUICK_CANCEL_PASS:-}" ]; then
    python manage.py create_quick_cancel_group \
        --username "$QUICK_CANCEL_USER" --password "$QUICK_CANCEL_PASS"
else
    python manage.py create_quick_cancel_group --no-user
fi

# Deactivate players inactive for 3+ years (goalies only by default)
python manage.py deactivate_inactive_players
