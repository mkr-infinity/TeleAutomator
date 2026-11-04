# Local Deployment Guide (Arch Linux & Standard Linux)

```text
========================================================================================
  Telegram Chat Automation v1.0
  ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
  Author:     Mohammad Kaif Raja (mkr-infinity)
  Telegram:   @mkr_infinity (https://t.me/mkr_infinity)
  Instagram:  @mkr_infinity (https://instagram.com/mkr_infinity)
  Copyright:  Copyright (c) Mohammad Kaif Raja. All Rights Reserved.
========================================================================================
```

This guide walks you through setting up and running your personal Telegram client locally on your Linux laptop.

---

## 🚀 Beginner Quick Start in 4 Steps

### Step 1: Run Local Setup
In your terminal, navigate to the project directory and run:
```bash
./local/setup.sh
```
What this does:
- Checks Python 3.10+
- Creates an isolated virtual environment in `.venv/`
- Installs all dependencies (`telethon`, `python-dotenv`, `pytest`)
- Prepares your private `.env` file with `0600` permissions
- Prepares your private `data/` directory with `0700` permissions

---

### Step 2: Configure Your Credentials
Open `.env` (e.g. `nano .env`):
```env
# 1. Telegram API (from https://my.telegram.org)
TG_API_ID=34656768
TG_API_HASH=7c7077f000e5a2da382562c27881a5fc

# 2. Google Gemini API Key (from https://aistudio.google.com/app/apikey)
AI_ENABLED=true
AI_PROVIDER=gemini
AI_API_KEY=your_gemini_api_key_here
AI_MODEL=gemini-3.5-flash

# 3. Automation Mode
REPLY_MODE=restricted_auto
AUTO_AUTHORIZE=true

# 4. Target Chats (Optional: you can also add them later from Telegram using /allowchat <id>)
ALLOWED_PRIVATE_CHATS=
ALLOWED_GROUPS=
```

---

### Step 3: First-Time Authentication
Run:
```bash
./local/authenticate.sh
```
1. Enter your phone number with country code (e.g., `+1234567890`).
2. Enter the 5-digit verification code sent to your Telegram app.
3. Enter your Two-Step Verification (2FA) password if enabled.
4. The script confirms authentication, creates your session file in `data/telegram_client.session` (`0600`), and exports your `TG_SESSION_STRING` for cloud VPS use.

---

### Step 4: Start the Client
Run:
```bash
./local/start.sh
```
The client will display the professional startup banner, connect to MTProto, and send a welcome guide to your **Telegram Saved Messages**!

---

## 📱 Telegram Saved Messages Commands

While the client is running, you can manage it directly by texting your **Saved Messages**:

- **`/status`** — Displays health, identity name, and pause status.
- **`/chats`** — Lists all active allowlisted private chats and groups.
- **`/allowchat <id>`** — Adds a contact or group to the allowlist instantly.
- **`/removechat <id>`** — Removes a chat from the allowlist.
- **`/addrule <word> => <reply>`** — Sets a custom auto-reply trigger for any word.
- **`/rules`** — Lists your custom keyword rules.
- **`/delrule <word>`** — Deletes a keyword rule.
- **`/pause 2h`** — Snoozes auto-replies for 2 hours (or any duration like `30m`).
- **`/resume`** — Resumes normal listening immediately.
- **`/mentiononly on|off`** — Group filter: replies only when mentioned in groups.
- **`/name <name>`** — Changes your persona name.
- **`/prompt`** — Views your active AI persona prompt.
- **`/setprompt <text>`** — Updates your AI prompt on the fly.
- **`/stop`** — Emergency kill switch (halts all replies).

---

## 🧪 Testing
To run the automated test suite locally:
```bash
./local/test.sh
```
Or verify account connection without sending messages:
```bash
source .venv/bin/activate
python3 scripts/check_connection.py
```

---

## 🔗 Related Documentation
- 📖 Main Complete Guide: [`README.md`](../README.md)
- ☁️ Cloud VPS 24/7 Deployment: [`cloud/README.md`](../cloud/README.md)
