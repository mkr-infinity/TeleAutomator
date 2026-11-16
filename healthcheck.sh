#!/bin/sh
# Same data directory the entrypoint resolved: Railway's volume path wins when present.
DATA_DIR="${RAILWAY_VOLUME_MOUNT_PATH:-${DATA_DIR:-/app/data}}"
export DATA_DIR
# The container starts as root so it can fix volume ownership; never run the check as root.
if [ "$(id -u)" = "0" ] && command -v setpriv >/dev/null 2>&1; then
    exec setpriv --reuid=10001 --regid=10001 --clear-groups python3 -m app.main --health
fi
exec python3 -m app.main --health
