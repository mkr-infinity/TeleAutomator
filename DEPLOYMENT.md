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
   - [Option A: Interactive File Session (Recommended for VPS)](#option-a-interactive-file-session-recommended)
   - [Option B: Headless StringSession (For Docker & Cloud PaaS)](#option-b-headless-stringsession-for-docker--cloud-paas)
8. [Step 7: Configure Environment Variables (.env)](#step-7-configure-environment-variables-env)
9. [Step 8: Launch 24/7 with Docker Compose (VPS)](#step-8-launch-247-with-docker-compose)
10. [Railway.app Deployment (Recommended Cloud PaaS)](#railwayapp-deployment-recommended-cloud-paas)
11. [Render.com Deployment (Free Cloud Hosting)](#rendercom-deployment-free-cloud-hosting)
    - [Method 1: One-Click Render Blueprint (render.yaml)](#method-1-one-click-render-blueprint-renderyaml)
    - [Method 2: Manual Render Web Service Setup](#method-2-manual-render-web-service-setup)
    - [Keeping Render Free Tier Alive 24/7](#keeping-render-free-tier-alive-247)
12. [Step 9: Test & Verify from Telegram](#step-9-test--verify-from-telegram)
13. [Step 10: Server Management & Updates](#step-10-server-management--updates)
14. [Troubleshooting & FAQ](#troubleshooting--faq)

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

## Railway.app Deployment (Recommended Cloud PaaS)

TeleAutomator comes pre-configured for **[Railway.app](https://railway.app)** with automated build detection via [`railway.json`](railway.json), [`Dockerfile`](Dockerfile), and [`Procfile`](Procfile).

### Step 1: Generate Your StringSession (Run Once Locally)
Cloud platforms do not permit interactive terminal prompts for SMS/OTP codes. You must generate a `TG_SESSION_STRING` on your computer first.

You have two options:

- **Option A (Dedicated Cloud Session - Recommended)**:
  Generates an independent session registered as a separate device. You can run locally AND on Railway simultaneously without conflict:
  ```bash
  ./session.sh --new
  # Or: python run.py --new-session
  ```

- **Option B (Export Existing Local Session)**:
  Exports your current local `.session` file to a string:
  ```bash
  ./session.sh
  # Or: python run.py --session
  ```

> [!CAUTION]
> **DO NOT RUN LOCAL AND CLOUD INSTANCES SIMULTANEOUSLY WITH THE SAME SESSION!**  
> If you export an existing local session (Option B), stop your local client before starting Railway. If Telegram MTProto detects the same session key connecting from two IP addresses at once, it permanently revokes the session with `AuthKeyDuplicatedError`. To run both concurrently, use Option A (`./session.sh --new`).

Copy the exported session string (starts with `1...`).

### Step 2: Deploy to Railway
1. Log into **[Railway.app](https://railway.app)** and click **New Project** -> **Deploy from GitHub repo**.
2. Select your repository. Railway will detect `railway.json` / `Dockerfile` and configure the build automatically.

### Step 3: Enter Environment Variables in Railway Dashboard
In your Railway service settings, go to the **Variables** tab and add the following:

| Variable | Recommended Value / Description |
| :--- | :--- |
| `TG_API_ID` | Your numeric Telegram API ID from `my.telegram.org` |
| `TG_API_HASH` | Your 32-character Telegram API Hash from `my.telegram.org` |
| `TG_SESSION_STRING` | Your exported session string from `./session.sh` |
| `AI_PROVIDER` | `gemini` (or `openai`, `custom`, `nvidia`, `groq`) |
| `AI_API_KEY` | Your AI provider API key (e.g. `AIzaSy...` for Gemini or `sk-...` for OpenAI/custom) |
| `AI_MODEL` | `gemini-2.5-flash` (or your model name, e.g. `gpt-4o-mini`) |
| `AI_BASE_URL` | Base endpoint URL (only needed for `custom` OpenAI-compatible providers, e.g. `https://api.your-provider.com/v1`) |
| `REASONING_EFFORT`| `low` (options: `low`, `medium`, `high`, `off`) |
| `REPLY_MODE` | `restricted_auto` (or `approval`, `draft`) |
| `AUTO_AUTHORIZE` | `true` |

Once saved, Railway will immediately trigger a build, pass health checks, and begin running 24/7!

---

## Render.com Deployment (Free Cloud Hosting)

If you do not want to manage a VPS, you can host TeleAutomator on **[Render.com](https://render.com)** for free.

### Why Render Needs a StringSession
Cloud platforms like Render do not allow interactive terminal typing to enter your Telegram login code. You must generate your session string once on your local computer before deploying.

#### Pre-Step: View or Generate Your Session String (1 Minute)
If you already authenticated locally using `./authenticate.sh` (local mode), view your exported cloud session string directly in your terminal:
```bash
./session.sh
# Or on Windows / cross-platform:
python run.py --session
```
*(If you have not authenticated yet, run `./authenticate.sh` or `python run.py --auth` first).*

- The terminal will display your complete string starting with `1...` (your `TG_SESSION_STRING`).
- Copy this entire string to use in Render.com or Docker.

---

### Method 1: One-Click Render Blueprint (render.yaml)

1. **Fork the Repository**:
   - Go to [https://github.com/mkr-infinity/TeleAutomator](https://github.com/mkr-infinity/TeleAutomator).
   - Click **Fork** (top-right) to copy the repository to your GitHub account.
2. **Log into Render**:
   - Visit **[https://dashboard.render.com](https://dashboard.render.com)** and sign in with GitHub.
3. **Deploy Blueprint**:
   - Click **New +** -> **Blueprint**.
   - Select your forked `TeleAutomator` repository.
   - Render automatically reads [`render.yaml`](render.yaml).
4. **Enter Your Secrets**:
   Render will prompt you for the following environment variables:
   - **`TG_API_ID`**: Your numeric API ID from `my.telegram.org`.
   - **`TG_API_HASH`**: Your 32-character API Hash from `my.telegram.org`.
   - **`TG_SESSION_STRING`**: The session string you generated above.
   - **`AI_API_KEY`**: Your Google Gemini API key (`AIzaSy...`).
5. Click **Apply**. Render will build and launch your service!

---

### Method 2: Manual Render Web Service Setup

If you prefer setting it up manually without a blueprint:

1. In Render Dashboard, click **New +** -> **Web Service**.
2. Connect your GitHub repository.
3. Configure the settings:
   - **Name**: `teleautomator`
   - **Language / Runtime**: `Python 3`
   - **Branch**: `main`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python3 -m app.main`
   - **Instance Type**: `Free`
4. Click **Advanced** -> **Add Environment Variable** and add each:

| Key | Value | Notes |
| :--- | :--- | :--- |
| `TG_API_ID` | `12345678` | From `my.telegram.org` |
| `TG_API_HASH` | `0123456789abcdef...` | From `my.telegram.org` |
| `TG_SESSION_MODE` | `string` | **Must be `string` on Render** |
| `TG_SESSION_STRING` | `1BVts...` | The string from `generate_session.py` |
| `AI_ENABLED` | `true` | Enables Google Gemini AI |
| `AI_PROVIDER` | `gemini` | Google Gemini |
| `AI_API_KEY` | `AIzaSy...` | From Google AI Studio |
| `REPLY_MODE` | `restricted_auto` | Hands-free auto-replying |
| `AUTO_AUTHORIZE` | `true` | Authorizes automated sends |
| `MIN_REPLY_DELAY_SECONDS` | `5` | Adaptive delay lower bound |
| `MAX_REPLY_DELAY_SECONDS` | `60` | Adaptive delay upper bound |
| `TYPING_DELAY_SECONDS` | `2` | Typing action duration |

5. Click **Create Web Service**.
6. TeleAutomator automatically detects Render's `$PORT` and starts an internal health check server on `/` and `/health`, ensuring Render marks the deployment as **Healthy**!

---

### Keeping Render Free Tier Alive 24/7

> [!NOTE]  
> Render's **Free Tier Web Services** automatically spin down into sleep mode after 15 minutes if no web requests are received.

To keep TeleAutomator awake and responding 24/7 on the Free tier:
1. Copy your Render web service URL (e.g. `https://teleautomator-xxxx.onrender.com`).
2. Go to a free website monitoring service such as:
   - **[UptimeRobot](https://uptimerobot.com)** (Free)
   - **[cron-job.org](https://cron-job.org)** (Free)
   - **[Better Stack](https://betterstack.com)** (Free)
3. Create a **New Monitor / Cron Job**:
   - **URL**: `https://teleautomator-xxxx.onrender.com`
   - **Interval**: Every 10 minutes (or 5 minutes)
   - **Method**: `HTTP GET`
4. TeleAutomator's built-in HTTP server will reply with `200 OK {"status":"healthy"}`. This keeps your free container permanently awake 24/7 without ever entering sleep mode!

*(Alternatively, upgrading to a Render Background Worker for $7/month runs 24/7 natively without needing web pings).*

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
  4. Railway will automatically redeploy and start listening 24/7!

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
- TeleAutomator isolates all alerts and errors to your private **Control Bot**. Nothing is ever leaked to groups or contacts.

---
*Maintained by Mohammad Kaif Raja ([@mkr_infinity](https://t.me/mkr_infinity)) • Repository: [TeleAutomator](https://github.com/mkr-infinity/TeleAutomator)*
