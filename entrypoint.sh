#!/bin/sh
set -eu
umask 0077

APP_UID=10001
APP_GID=10001

DATA_DIR="${DATA_DIR:-/app/data}"
# Railway reports where its volume is mounted. Data must live there to survive redeploys,
# so follow it if the mount path is ever changed in the dashboard.
if [ -n "${RAILWAY_VOLUME_MOUNT_PATH:-}" ]; then
    DATA_DIR="$RAILWAY_VOLUME_MOUNT_PATH"
fi
export DATA_DIR

# Cloud storage is required even when the Telegram credential is a string.
if [ "${REQUIRE_PERSISTENT_STORAGE:-false}" = "true" ] || [ -n "${RAILWAY_ENVIRONMENT:-}${RAILWAY_ENVIRONMENT_ID:-}${RENDER:-}" ]; then
    python3 -c 'import os, sys; sys.exit(0 if os.path.ismount(os.environ["DATA_DIR"]) else 1)' || {
        echo "[FATAL] Mount a persistent volume at DATA_DIR ($DATA_DIR) before starting; without it every redeploy erases settings, memory and approvals." >&2
        exit 1
    }
fi

# Hosts mount volumes as root. Fix ownership once, then drop root before any app code runs.
if [ "$(id -u)" = "0" ]; then
    mkdir -p "$DATA_DIR"
    if [ "$(stat -c %u "$DATA_DIR")" != "$APP_UID" ]; then
        chown -R "$APP_UID:$APP_GID" "$DATA_DIR" || echo "[WARN] Could not change ownership of $DATA_DIR." >&2
    fi
    chmod 700 "$DATA_DIR" 2>/dev/null || true
    command -v setpriv >/dev/null 2>&1 || {
        echo "[FATAL] setpriv is missing, so the container cannot drop root privileges." >&2
        exit 1
    }
    exec setpriv --reuid="$APP_UID" --regid="$APP_GID" --clear-groups "$0" "$@"
fi

mkdir -p "$DATA_DIR"
[ -w "$DATA_DIR" ] && [ -x "$DATA_DIR" ] || {
    echo "[FATAL] DATA_DIR ($DATA_DIR) is not writable by UID $(id -u). Start the container as root so it can fix ownership." >&2
    exit 1
}
if [ -n "${RAILWAY_ENVIRONMENT:-}${RAILWAY_ENVIRONMENT_ID:-}${RENDER:-}" ] && [ "${TG_SESSION_MODE:-string}" != "string" ]; then
    echo "[FATAL] Hosted deployments require TG_SESSION_MODE=string." >&2
    exit 1
fi
session_mode="${TG_SESSION_MODE:-}"
if [ -z "$session_mode" ]; then
    if [ -n "${TG_SESSION_STRING:-}" ]; then session_mode=string; else session_mode=local; fi
fi
case "$session_mode" in
    string)
        [ -n "${TG_SESSION_STRING:-}" ] || {
            echo "[FATAL] TG_SESSION_STRING is empty; generate a dedicated session with ./session.sh --new." >&2
            exit 1
        }
        ;;
    local)
        session_file="${TG_SESSION_NAME:-telegram_client}"
        case "$session_file" in *.session) ;; *) session_file="$session_file.session" ;; esac
        [ -s "$DATA_DIR/$session_file" ] || {
            echo "[FATAL] Local session missing in $DATA_DIR. Set TG_SESSION_MODE=string with TG_SESSION_STRING (see DEPLOYMENT.md)." >&2
            exit 1
        }
        ;;
    *) echo "[FATAL] TG_SESSION_MODE must be local or string." >&2; exit 1 ;;
esac
exec "$@"
