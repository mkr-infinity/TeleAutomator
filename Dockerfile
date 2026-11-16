# Non-root container for Telegram Chat Automation
FROM python:3.12-slim

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/app/data

# Create non-root user and group
RUN groupadd -g 10001 appuser && \
    useradd -u 10001 -g appuser -s /bin/bash -m appuser

WORKDIR /app

# Install runtime dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code, scripts, and prompt configuration
COPY app/ ./app/
COPY miniapp/ ./miniapp/
COPY scripts/ ./scripts/
COPY system_prompt.txt* ./
COPY entrypoint.sh ./entrypoint.sh
COPY healthcheck.sh ./healthcheck.sh
COPY Procfile* ./
COPY railway.json* ./

# Prepare data directory and enforce ownership
RUN mkdir -p /app/data && \
    chown -R appuser:appuser /app && \
    chmod 700 /app/data && \
    chmod +x /app/entrypoint.sh /app/healthcheck.sh

# The container starts as root only so entrypoint.sh can fix ownership of a root-owned
# volume (Railway mounts volumes as root). It drops to appuser (10001) before the app runs.

# Health check using self-contained python health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD /app/healthcheck.sh

EXPOSE 8080

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python3", "-m", "app.main"]
