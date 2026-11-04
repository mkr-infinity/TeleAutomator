# TeleAutomator - 24/7 Cloud Deployment & Account Setup Guide

> **Zero-Skip Step-by-Step Walkthrough for Beginners**  
> Learn how to deploy TeleAutomator on a 24/7 cloud server (VPS/Docker) and connect your Telegram account safely.

---

## 📑 Table of Contents
1. [Prerequisites](#1-prerequisites)
2. [Step 1: Get a Cloud VPS Server](#step-1-get-a-cloud-vps-server)
3. [Step 2: Obtain Telegram API Credentials (my.telegram.org)](#step-2-obtain-telegram-api-credentials-mytelegramorg)
4. [Step 3: Get a Free Google Gemini API Key](#step-3-get-a-free-google-gemini-api-key)
5. [Step 4: Connect to Server & Clone Repository](#step-4-connect-to-server--clone-repository)
6. [Step 5: Run Automated Server Setup](#step-5-run-automated-server-setup)
7. [Step 6: Authenticate Your Telegram Account](#step-6-authenticate-your-telegram-account)
   - [Option A: Interactive File Session (Recommended)](#option-a-interactive-file-session-recommended)
   - [Option B: Headless StringSession (For Docker & Cloud PaaS)](#option-b-headless-stringsession-for-docker--cloud-paas)
8. [Step 7: Configure Environment Variables (.env)](#step-7-configure-environment-variables-env)
9. [Step 8: Launch 24/7 with Docker Compose](#step-8-launch-247-with-docker-compose)
10. [Step 9: Test & Verify from Telegram](#step-9-test--verify-from-telegram)
11. [Step 10: Server Management & Updates](#step-10-server-management--updates)
12. [Troubleshooting & FAQ](#troubleshooting--faq)

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

1. Choose any cloud provider:
   - **Hetzner** (~$4/month - CX22)
   - **DigitalOcean** (~$4-6/month - Basic Droplet)
   - **AWS Lightsail** (~$3.50/month)
   - **Linode / Akamai** (~$5/month)
   - **Vultr** (~$3.50/month)
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

## Step 3: Get a Free Google Gemini API Key

TeleAutomator uses Google Gemini 3.5 Flash for natural, context-aware human replies.

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

TeleAutomator includes an auto-detecting setup script that installs Python, virtual environments, Docker, and dependencies automatically:

```bash
./setup.sh
```

*(The script automatically detects Debian/Ubuntu, verifies Python 3.10+, creates a secure `.venv`, and creates `.env` from template).*

---

## Step 6: Authenticate Your Telegram Account

Choose either Option A (simplest) or Option B (best for ephemeral clouds):

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
   python3 scripts/generate_session.py
   ```
2. Enter your phone number, code, and 2FA password.
3. The script will output an encrypted string starting with `1...`.
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

# 3. Allowlist (Leave empty initially; authorize chats via Saved Messages later)
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

Deploy the hardened, non-root Docker container:

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

---

## Step 9: Test & Verify from Telegram

You never need to log into the server again for everyday tasks. Everything is managed through your Telegram **Saved Messages** (chat with yourself):

1. Open Telegram on your phone.
2. Go to **Saved Messages**.
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
- TeleAutomator isolates all errors to your private **Saved Messages**. Nothing is ever leaked to groups or contacts.

---
*Maintained by Mohammad Kaif Raja ([@mkr_infinity](https://t.me/mkr_infinity)) • Repository: [TeleAutomator](https://github.com/mkr-infinity/TeleAutomator)*
