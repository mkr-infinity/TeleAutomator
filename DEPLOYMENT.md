# TeleAutomator - 24/7 Cloud Deployment & Account Setup Guide

> **Zero-Skip Step-by-Step Walkthrough for Beginners**  
> Learn how to deploy TeleAutomator on a 24/7 cloud server (VPS/Docker) and connect your Telegram account safely.  
> Looking for a breakdown of every `.env` variable and where to find keys? See **[REQUIREMENTS.md](REQUIREMENTS.md)**.

---

## 📑 Table of Contents
1. [Prerequisites](#1-prerequisites)
2. [Step 1: Get a Cloud VPS Server](#step-1-get-a-cloud-vps-server)
3. [Step 2: Obtain Telegram API Credentials (my.telegram.org)](#step-2-obtain-telegram-api-credentials-mytelegramorg)
4. [Step 3: Get a Google Gemini API Key](#step-3-get-a-google-gemini-api-key)
5. [Step 4: Connect to Server & Clone Repository](#step-4-connect-to-server--clone-repository)
6. [Step 5: Run Automated Server Setup](#step-5-run-automated-server-setup)
7. [Step 6: Authenticate Your Telegram Account](#step-6-authenticate-your-telegram-account)
   - [Option A: Interactive File Session (Recommended for VPS)](#option-a-interactive-file-session-recommended)
   - [Option B: Headless StringSession (For Docker & Cloud PaaS)](#option-b-headless-stringsession-for-docker--cloud-paas)
8. [Step 7: Configure Environment Variables (.env)](#step-7-configure-environment-variables-env)
9. [Step 8: Launch 24/7 with Docker Compose (VPS)](#step-8-launch-247-with-docker-compose)
10. [Railway and Render](#railway-recommended-for-247-hosting)
11. [Step 9: Test & Verify from Telegram](#step-9-test--verify-from-telegram)
12. [Step 10: Server Management & Updates](#step-10-server-management--updates)
13. [Troubleshooting & FAQ](#troubleshooting--faq)

---

## 1. Prerequisites

Before starting, ensure you have:
- An active Telegram account with a phone number.
- A computer or phone with terminal/SSH capability.
- 10 minutes of time.
- Zero prior coding experience needed—every command is copy-pasteable.

---

## Step 1: Get a Cloud VPS Server

To keep TeleAutomator running 24/7 while your laptop is closed, you need a lightweight Linux server (VPS).

1. Choose your host, region, resources, and cost explicitly before creating a server.
   This guide does not select a provider or assume current prices or available plans.
2. Select the OS: **Ubuntu 24.04 LTS** or **Debian 12**.
3. Once the server is created, open your terminal (PowerShell on Windows, Terminal on macOS/Linux) and log in:
   ```bash
   ssh root@YOUR_SERVER_IP
   ```
   *(Replace `YOUR_SERVER_IP` with the IP address provided by your cloud host).*

---

## Step 2: Obtain Telegram API Credentials (my.telegram.org)

Telegram requires an `api_id` and `api_hash` to connect MTProto personal clients.

1. Open your browser and go to: **[https://my.telegram.org](https://my.telegram.org)**.
2. Enter your phone number in international format (e.g., `+1234567890` or `+919876543210`) and click **Next**.
3. Open Telegram on your phone/desktop. You will receive a login message from Telegram containing a confirmation code.
4. Copy the confirmation code, paste it into the browser window, and click **Sign In**.
5. Click **API development tools**.
6. Fill in the short application form:
   - **App title**: `TeleAutomator`
   - **Short name**: `teleautomator`
   - **URL**: Leave empty or enter `https://github.com/mkr-infinity/TeleAutomator`
   - **Platform**: Select `Desktop` or `Other`
7. Click **Create application**.
8. You will now see your credentials:
   - **`api_id`**: A numeric ID (e.g. `12345678`)
   - **`api_hash`**: A 32-character hexadecimal string (e.g. `0123456789abcdef0123456789abcdef`)
9. Keep this tab open or save these two values in a safe place.

---

## Step 3: Get a Google Gemini API Key

Configure a model available to your own provider account. Gemini is one supported provider; check your account limits and charges before enabling requests.

1. Go to: **[Google AI Studio](https://aistudio.google.com/app/apikey)**.
2. Sign in with your Google account.
3. Click **Create API Key**.
4. Select a project (or click **Create new project**) and click **Create key**.
5. Copy your generated key (starts with `AIzaSy...`).

---

## Step 4: Connect to Server & Clone Repository

Inside your server SSH terminal, run:

```bash
# Update package list and install git & curl
sudo apt update && sudo apt install -y git curl

# Clone the repository
git clone https://github.com/mkr-infinity/TeleAutomator.git

# Enter project directory
cd TeleAutomator
```

---

## Step 5: Run Automated Server Setup

TeleAutomator includes an auto-detecting setup script that checks an existing Python 3.10+ installation and installs Python dependencies into a virtual environment:

```bash
./setup.sh
```

*(The script automatically detects Debian/Ubuntu, verifies Python 3.10+, creates a secure `.venv`, and creates `.env` from template).*

---

## Step 6: Authenticate Your Telegram Account

Use a file session when you run TeleAutomator directly on a server (`./start.sh`). Use a StringSession for Docker, Railway and Render. Containers also need durable storage for the database and chat memory (see below).

### Option A: Interactive File Session (Recommended)

Run the built-in login script in your SSH terminal:

```bash
./authenticate.sh
```

1. **Enter Phone Number**: Type your phone number with country code (e.g. `+919876543210`).
2. **Enter Telegram Code**: Check your Telegram app for the 5-digit login code and enter it.
3. **Two-Step Verification (2FA)**: If you have a cloud password enabled, type it when prompted (characters will be hidden for security).
4. **Success!** The session is saved to `data/telegram_client.session` with secure permissions (`0600`).

---

### Option B: Headless StringSession (For Docker & Cloud PaaS)

If you prefer keeping your session in an environment variable rather than a file:

1. Generate a StringSession:
   ```bash
   python run.py --new-session
   ```
2. Enter your phone number, code, and 2FA password.
3. The script outputs an encoded bearer credential, not an encrypted string. Local session files are also unencrypted; use filesystem permissions and disk encryption as appropriate.
4. Copy the entire string.
5. In `.env`, set:
   ```env
   TG_SESSION_MODE=string
   TG_SESSION_STRING=PASTE_YOUR_STRING_HERE
   ```

---

## Step 7: Configure Environment Variables (.env)

Open `.env` with a terminal editor:

```bash
nano .env
```

Ensure the following values are filled in:

```env
# 1. Telegram API Credentials from Step 2
TG_API_ID=12345678
TG_API_HASH=0123456789abcdef0123456789abcdef

# 2. Session Settings
TG_SESSION_MODE=local
TG_SESSION_NAME=telegram_client

# 3. Allowlist (Leave empty initially; authorize chats via Control Bot later)
ALLOWED_PRIVATE_CHATS=
ALLOWED_GROUPS=

# 4. Reply Mode
# Use "approval" to review replies first, or "restricted_auto" for hands-free automation
REPLY_MODE=restricted_auto
AUTO_AUTHORIZE=true

# 5. AI Configuration from Step 3
AI_ENABLED=true
AI_PROVIDER=gemini
AI_API_KEY=AIzaSyYourGeminiApiKeyHere
AI_MODEL=gemini-3.5-flash

# 6. Safety Cooldowns & Human Delay
GLOBAL_COOLDOWN_SECONDS=30
PER_CHAT_COOLDOWN_SECONDS=60
MIN_REPLY_DELAY_SECONDS=5
MAX_REPLY_DELAY_SECONDS=60
TYPING_DELAY_SECONDS=2
```

Save and exit: press `Ctrl + O`, then `Enter`, then `Ctrl + X`.

---

## Step 8: Launch 24/7 with Docker Compose

Compose keeps settings, history and chat memory in a **named Docker volume** (`app_data`).
Docker creates it, the container fixes its ownership at start, and it survives rebuilds and
`docker compose down`. Your host `./data` folder is never touched.

Containers use a StringSession. Generate a dedicated one on your computer (the local sender must
not run at the same time) and put it in `.env`:

```bash
./session.sh --new          # Windows: python run.py --new-session
```

```env
TG_SESSION_MODE=string
TG_SESSION_STRING=PASTE_THE_STRING_HERE
```

Then start it:

```bash
# Build and start container in background
docker compose up -d --build

# View live logs to ensure startup succeeded
docker compose logs -f
```

You should see the startup banner and:
```text
[INFO] TeleAutomator personal client is running and listening for events.
```

Press `Ctrl + C` to detach from logs. The container will remain running 24/7 in the background and will restart automatically if the server reboots.

**Back up the volume** (stop the service first, and keep the file private):

```bash
docker compose stop
docker run --rm -v teleautomator_app_data:/data -v "$PWD":/backup python:3.12-slim \
  tar czf /backup/teleautomator-data.tgz -C /data .
docker compose start
```

Never run `docker compose down -v`: it deletes the volume.

---

## Railway (recommended for 24/7 hosting)

Railway builds the repository's `Dockerfile` (`railway.json`) and checks `/api/health` before it
switches a deployment live. That check only passes once Telegram is connected.

**One-time setup**

1. Create a service from your GitHub repository.
2. **Add a Volume** to the service (Service -> Settings -> Volumes) and mount it at `/app/data`.
   A service can have one volume. The container refuses to start without one, because Railway's
   filesystem is erased on every deploy and you would lose settings, chat memory and approvals.
3. Open the **Variables** tab and set:

```env
TG_API_ID=YOUR_ID
TG_API_HASH=YOUR_HASH
TG_SESSION_MODE=string
TG_SESSION_STRING=YOUR_DEDICATED_SESSION
AI_ENABLED=true
AI_PROVIDER=YOUR_PROVIDER
AI_API_KEY=YOUR_KEY
AI_MODEL=YOUR_MODEL
BOT_API_KEY=YOUR_BOT_TOKEN
BOT_AUTHORIZED_USERS=YOUR_TELEGRAM_ID
REPLY_MODE=draft
```

4. Generate the dedicated session on your computer with `./session.sh --new` and stop the local
   sender before deploying. Treat the string like a password.
5. Deploy, then open the service's public domain to use the Mini App. Start in `draft` mode, review
   the behaviour, then switch to automatic replies from the bot or Mini App.

**Why this keeps working after changes**

- Railway mounts volumes as root. The container starts as root only to fix ownership, then drops
  to an unprivileged user (UID 10001) before the application runs. You do **not** need
  `RAILWAY_RUN_UID`.
- If you change the volume's mount path, the app follows `RAILWAY_VOLUME_MOUNT_PATH`
  automatically. Re-attaching or restoring a volume also works; ownership is repaired at start.
- Redeploys with a volume attached have a short downtime (Railway never runs two copies on one
  volume). That is expected and protects the SQLite database.
- Use one instance per Telegram account. Do not add replicas.

**Back up and verify**: enable Railway's volume backups, and check the deploy logs for the
startup banner. A successful build alone does not prove Telegram is connected; the health check
does.

## Render

`render.yaml` selects the Docker runtime and sets `REQUIRE_PERSISTENT_STORAGE=true`. It does not
create a disk or choose a plan. Add a persistent disk mounted at `/app/data` and pick your plan in
Render before applying it. The same variables as above apply.

---

## Step 9: Test & Verify from Telegram

You never need to log into the server again for everyday tasks. Everything is managed through your Telegram **Control Bot**:

1. Open Telegram on your phone.
2. Open your **Control Bot**.
3. Send:
   ```text
   /status
   ```
   TeleAutomator will reply with your active client status, current mode, style, and active filters.
4. **Authorizing a Chat**:
   When a contact messages you, check your server logs or send:
   ```text
   /allowchat 123456789
   ```
   *(Replace with your friend's user ID)*.
5. **Switching AI Styles**:
   ```text
   /style concise
   ```
6. **Setting Emergency Stop**:
   ```text
   /stop
   ```

---

## Step 10: Server Management & Updates

### Useful Docker Commands
```bash
# Check container status & health
docker compose ps

# View live streaming logs
docker compose logs -f --tail=100

# Restart the application
docker compose restart

# Stop the application
docker compose down
```

### Updating to the Latest Version
```bash
cd ~/TeleAutomator
git pull origin main
docker compose up -d --build
```

---

## Troubleshooting & FAQ

### Q: I received "The authorization key (session file) was used under two different IP addresses simultaneously (AuthKeyDuplicatedError)"
- **Why this happens**: Telegram MTProto has strict anti-hijacking security. If the same authorization key is connected from two IP addresses at the same time (e.g. running TeleAutomator on your home PC while deployed to Railway), Telegram immediately and permanently revokes the authorization key.
- **How to fix**:
  1. If running locally, stop your local client.
  2. Generate a dedicated cloud session by running:
     ```bash
     ./session.sh --new
     # Or on Windows: python run.py --new-session
     ```
  3. Copy the newly generated string session and update `TG_SESSION_STRING` in your Railway dashboard (under the **Variables** tab).
  4. Verify the volume mount, startup logs, and health before enabling replies.

### Q: I received "Telegram API Error: PHONE_CODE_INVALID"
- Telegram verification codes expire in a few minutes. Re-run `./authenticate.sh` and enter the newest code immediately.

### Q: "Cannot connect to Telegram / Network timeout"
- Some VPS providers block outgoing port 443 or MTProto IPs. Ensure your server firewall allows outbound traffic:
  ```bash
  sudo ufw allow out 443/tcp
  ```

### Q: Does my phone need to stay online?
- **No**. The server runs independently 24/7. Your phone can be turned off, in airplane mode, or offline, and TeleAutomator will continue running.

### Q: Where do errors go?
- Inspect private server logs and the configured control channel. Logs and runtime state must be protected; error handling is not a guarantee that all third-party errors are private.

---
*Maintained by Mohammad Kaif Raja ([@mkr_infinity](https://t.me/mkr_infinity)) • Repository: [TeleAutomator](https://github.com/mkr-infinity/TeleAutomator)*
