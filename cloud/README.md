# Cloud Deployment Guide (Docker & Linux VPS)

This directory contains the production-ready Docker Compose configuration for running your personal Telegram MTProto client 24/7 on a Linux VPS without requiring your laptop to remain switched on.

---

## 🔒 Cloud Architecture & Security Principles

1. **No Interactive Login on Server**: The cloud container never asks for SMS codes or passwords. Instead, it uses a pre-authenticated **MTProto StringSession (`TG_SESSION_STRING`)** generated on your local laptop.
2. **Non-Root Execution**: Runs under unprivileged user `appuser` (UID `10001`).
3. **No Inbound Web Ports**: Telegram MTProto is an outbound long-polling/TCP socket protocol. No public web ports or HTTP proxies are opened to the internet.
4. **Isolated Volume**: Stores deduplication and approval queue state in Docker named volume `cloud_data` mounted at `/app/data`.
5. **Restart Policy**: `restart: unless-stopped` guarantees the client restarts after server reboot or transient crashes.

---

## 📋 Prerequisites

On your cloud server (e.g., Ubuntu, Debian, Arch Linux VPS):
- Docker installed (`sudo apt install docker.io` or distro equivalent)
- Docker Compose plugin installed (`docker compose version`)

---

## 🚀 Step-by-Step Deployment

### Step 1: Generate Cloud Session on Local Laptop
On your local computer, run:
```bash
python3 scripts/generate_session.py
```
*(Or use `./local/authenticate.sh` which prints the string session upon first login).*
Copy the resulting `TG_SESSION_STRING` value.

---

### Step 2: Copy Project to Cloud Server
Copy or clone the project folder to your VPS:
```bash
rsync -avz --exclude='.venv' --exclude='data' ./ user@your-server-ip:~/telegram-chat-automation/
```

---

### Step 3: Configure Cloud Environment
SSH into your server and enter the `cloud/` directory:
```bash
cd ~/telegram-chat-automation/cloud
cp .env.example .env
chmod 600 .env
nano .env
```

Set the following variables in `cloud/.env`:
```env
TG_API_ID=your_api_id
TG_API_HASH=your_api_hash

# Set session mode to 'string' and paste your session string
TG_SESSION_MODE=string
TG_SESSION_STRING=1ApWapzIBu3h4...[paste full session string]

# Reply Mode: approval (recommended for cloud) or restricted_auto
REPLY_MODE=approval

# Explicit Allowlist (Only messages from these IDs will ever be processed)
ALLOWED_PRIVATE_CHATS=123456789
ALLOWED_GROUPS=

# Rates and Limits
GLOBAL_COOLDOWN_SECONDS=30
PER_CHAT_COOLDOWN_SECONDS=60
MAX_MESSAGE_LENGTH=1000

DATA_DIR=/app/data
```

---

### Step 4: Build and Launch
Deploy using the automated script:
```bash
./deploy.sh
```
Or directly with Docker Compose:
```bash
docker compose build
docker compose up -d
```

---

## 🎮 Managing the Cloud Deployment

### View Realtime Logs
```bash
docker compose logs -f
```
*(Notice that all phone numbers, API hashes, and session keys are automatically redacted in logs!)*

### Check Health & Container Status
```bash
docker compose ps
```
The status will display `Up (healthy)`.

### Restart Container
```bash
docker compose restart
```

### Stop Container Cleanly
```bash
docker compose down
```

### Update Code
When you push code updates:
```bash
git pull
docker compose build
docker compose up -d
```

---

## 📱 Controlling the Remote Client from Telegram

When running in `REPLY_MODE=approval`:
1. Whenever someone in your allowlist messages you, the cloud client sends a private notification to your **Saved Messages**:
   ```text
   📝 Pending Approval #12
   • Chat: Client Bob (987654321)
   • Incoming: "Are you ready to discuss the project?"
   • Suggested Reply: "Yes, ready when you are! Let me know."
   Send /approve 12 to send, or /reject 12 to discard.
   ```
2. Simply reply in Saved Messages:
   - `/approve 12` — Dispatches the message through your personal account.
   - `/reject 12` — Discards the draft.
   - `/status` — Displays remote server uptime and health.
   - `/auto on` — Temporarily authorizes automatic sending for low-risk messages.
   - `/auto off` — Revokes automatic sending.
   - `/stop` — Emergency pause switch to immediately cut off all outgoing messages.
   - `/resume` — Re-enables messaging after a pause.

---

## ⚠️ Important Operating Warnings

- **Never Run Local and Cloud Concurrently**: Operating two instances using the same Telegram session at the same instant can trigger MTProto session invalidation (`SESSION_REVOKED`). Stop your local instance (`Ctrl+C`) before starting the cloud container.
- **Revoking Compromised Cloud Instances**: If your VPS is compromised, immediately open Telegram on your phone:
  **Settings → Devices → Terminate all other sessions**.
