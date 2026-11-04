# Cloud VPS 24/7 Deployment Guide (Docker Compose)

```text
========================================================================================
  ProtoFlow: Telegram Chat Automation v1.0
  ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
  Author:     Mohammad Kaif Raja (mkr-infinity)
  Telegram:   @mkr_infinity (https://t.me/mkr_infinity)
  Instagram:  @mkr_infinity (https://instagram.com/mkr_infinity)
  Copyright:  Copyright (c) Mohammad Kaif Raja. All Rights Reserved.
========================================================================================
```

This guide explains how to deploy your personal Telegram client to a Linux VPS (Ubuntu, Debian, Arch Linux, etc.) using Docker Compose so it stays online 24/7 without requiring your laptop to stay powered on.

---

## 🔒 Security & Architecture Principles

1. **No Interactive Login on the VPS**: The container never asks for SMS codes or passwords. It uses an official **MTProto StringSession (`TG_SESSION_STRING`)** pre-authenticated safely on your laptop.
2. **Hardened Non-Root Container**: Runs under unprivileged user `appuser` (UID `10001`).
3. **No Inbound Open Web Ports**: Telegram MTProto uses outbound TCP connections to Telegram data centers. No open HTTP ports or web dashboards are exposed.
4. **Persistent Named Volume**: Docker volume `cloud_data` mounts at `/app/data` to persist deduplication, keyword rules, and approval queues.
5. **Auto-Restart**: `restart: unless-stopped` guarantees automatic recovery after server reboots.

---

## 🚀 Beginner Quick Start in 4 Steps

### Step 1: Export Your StringSession on Your Laptop
On your local laptop (after running `./local/authenticate.sh` at least once):
```bash
python3 scripts/generate_session.py
```
Copy the full `1ApWapzIBu...` string displayed.

---

### Step 2: Copy Code to Your Cloud VPS
From your laptop, copy the project directory to your VPS:
```bash
rsync -avz --exclude='.venv' --exclude='data' ./ user@YOUR_SERVER_IP:~/telegram-chat-automation/
```

---

### Step 3: Configure Cloud Environment on Server
SSH into your server:
```bash
ssh user@YOUR_SERVER_IP
cd ~/telegram-chat-automation/cloud
cp .env.example .env
chmod 600 .env
nano .env
```
Fill in your secrets:
```env
TG_API_ID=34656768
TG_API_HASH=7c7077f000e5a2da382562c27881a5fc

# Set string session mode and paste your exported session
TG_SESSION_MODE=string
TG_SESSION_STRING=1ApWapzIBu...paste_your_string_session_here...

# Enable Gemini AI
AI_ENABLED=true
AI_PROVIDER=gemini
AI_API_KEY=your_gemini_api_key_here
AI_MODEL=gemini-3.5-flash

# Mode
REPLY_MODE=restricted_auto
AUTO_AUTHORIZE=true

# Persistent volume directory
DATA_DIR=/app/data
```
Save and exit (`Ctrl+O`, `Enter`, `Ctrl+X`).

---

### Step 4: Build and Launch
Run:
```bash
./deploy.sh
```
Or directly with Docker Compose:
```bash
docker compose build
docker compose up -d
```

The container will build, start in the background, and immediately send an onboarding welcome message to your **Telegram Saved Messages**!

---

## 🛠️ Management Commands

- **View Live Logs**:
  ```bash
  docker compose logs -f
  ```
- **Check Health Status**:
  ```bash
  docker compose ps
  ```
  *(Status will show `Up (healthy)`).*
- **Restart Container**:
  ```bash
  docker compose restart
  ```
- **Stop Container**:
  ```bash
  docker compose down
  ```

---

## 📱 Controlling the Remote VPS Client from Your Phone

You do not need to SSH into your server to manage the client. Simply text commands to your **Saved Messages**:

- **`/status`** — Check VPS uptime, identity name, and pause timers.
- **`/chats`** — View all active allowlisted chats.
- **`/allowchat <id>`** — Add a new group or contact without touching `.env`.
- **`/addrule <word> => <reply>`** — Add custom instant keyword responses.
- **`/pause 2h`** — Snooze automated replies for 2 hours.
- **`/resume`** — Unpause and resume operations.
- **`/stop`** — Emergency kill switch (halts all outgoing replies immediately).
- **`/setprompt <text>`** — Updates the AI prompt on your VPS on the fly.

---

## ⚠️ Important Operating Warnings

- **Never Run Local and Cloud Instances Concurrently**: Using the same Telegram session on two computers at the exact same time can cause Telegram to invalidate the session (`SESSION_REVOKED`). Stop your local laptop client before starting the cloud container.
- **Revoking Compromised Instances**: If your VPS is ever compromised, immediately open Telegram on your phone:
  **Settings → Devices → Terminate all other sessions**.

---

## 🔗 Related Documentation
- 📖 Main Complete Guide: [`README.md`](../README.md)
- 💻 Local Laptop Deployment: [`local/README.md`](../local/README.md)
