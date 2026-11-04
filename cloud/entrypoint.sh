#!/bin/sh
set -e

# Restrict default file creation permissions to owner only
umask 0077

# Ensure data directory exists and has correct ownership
mkdir -p /app/data

# Basic check for required cloud session configuration
if [ "$TG_SESSION_MODE" = "string" ] && [ -z "$TG_SESSION_STRING" ]; then
    echo "[FATAL] TG_SESSION_MODE is set to 'string', but TG_SESSION_STRING is empty!" >&2
    echo "Please set TG_SESSION_STRING in your cloud environment variables." >&2
    exit 1
fi

exec "$@"
