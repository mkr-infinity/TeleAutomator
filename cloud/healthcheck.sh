#!/bin/sh
set -e

# Run built-in application health check
python3 -m app.main --health
