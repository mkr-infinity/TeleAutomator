# telegram-chat-automation v1.0

```text
========================================================================================
  ProtoFlow: Telegram Chat Automation v1.0
  ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

  A production-ready automation tool for automating whole telegram messages from
  bot-bot, account-bot, groups messages etc all from your main account.

  Author:     Mohammad Kaif Raja (mkr-infinity)
  Telegram:   @mkr_infinity (https://t.me/mkr_infinity)
  Instagram:  @mkr_infinity (https://instagram.com/mkr_infinity)
  Copyright:  Copyright (c) Mohammad Kaif Raja. All Rights Reserved.
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
~  If you modify, redistribute, or sell anything made from my things without my         ~
~  permission, it is strictly prohibited. Free to use for personal use.                 ~
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
  Unauthorized removal of attribution is strictly prohibited.
========================================================================================
```

---

## 📑 Complete Table of Contents
1. [Overview & What This Application Does](#1-overview--what-this-application-does)
2. [Differences: Telegram Bot vs. Personal MTProto Account](#2-differences-telegram-bot-vs-personal-mtproto-account)
3. [Architecture & Folder Structure](#3-architecture--folder-structure)
4. [Step-by-Step Beginner Setup Guide](#4-step-by-step-beginner-setup-guide)
   - [Step 4.1: Getting Telegram API Credentials (my.telegram.org)](#step-41-getting-telegram-api-credentials-mytelegramorg)
   - [Step 4.2: Getting a Free Google Gemini API Key](#step-42-getting-a-free-google-gemini-api-key)
   - [Step 4.3: Local Installation & Configuration](#step-43-local-installation--configuration)
   - [Step 4.4: First-Time Phone & 2FA Authentication](#step-44-first-time-phone--2fa-authentication)
   - [Step 4.5: Finding & Setting Chat IDs](#step-45-finding--setting-chat-ids)
   - [Step 4.6: Running the Client](#step-46-running-the-client)
5. [Telegram Saved Messages Control Center (Interactive Commands)](#5-telegram-saved-messages-control-center-interactive-commands)
6. [Setting Custom Keyword Trigger Rules From Telegram](#6-setting-custom-keyword-trigger-rules-from-telegram)
7. [Group Chat Automation & Mention Filters](#7-group-chat-automation--mention-filters)
8. [Anti-Scam & Link Protection System](#8-anti-scam--link-protection-system)
9. [Human Persona & Language Matching (Hindi + English)](#9-human-persona--language-matching-hindi--english)
10. [Local Deployment Guide (Reference)](#10-local-deployment-guide-reference)
11. [Cloud VPS 24/7 Deployment Guide (Reference)](#11-cloud-vps-247-deployment-guide-reference)
12. [Emergency Kill Switch & Safety Guards](#12-emergency-kill-switch--safety-guards)
13. [Troubleshooting & FAQ](#13-troubleshooting--faq)
14. [License & Attribution](#14-license--attribution)

---

## 1. Overview & What This Application Does

**telegram-chat-automation** is a production-grade Telegram client built with **Python 3**, **Telethon (MTProto)**, and **Google Gemini AI**.

Unlike simple bot scripts, this software connects directly as your **actual personal Telegram account**. It operates seamlessly in both private chats and groups you belong to, providing:
- **Intelligent Context-Aware Replies**: Generates natural, human-sounding replies in your personal texting tone.
- **Bilingual Matching**: Automatically replies in casual Hindi/Hinglish when messaged in Hindi, and in casual English when messaged in English.
- **Human Alibi (Anti-AI Disclosure)**: If someone asks *"are you an AI?"* or *"what model are you using?"*, it laughs it off as a human typing on their phone (e.g. *"model? mai toh bas phone se type kar raha hu bhai 😂"*).
- **Anti-Scam & Phishing Blocker**: Automatically drops messages containing suspicious crypto baits, Telegram channel invite links (`t.me/+...`), or URL shorteners.
- **Zero Outgoing Links**: The AI is strictly blocked from ever sending links or invites.
- **Custom Keyword Triggers**: Set instant custom auto-replies for specific keywords (e.g., `/addrule pricing => We will share pricing shortly`).
- **Remote Control from Your Phone**: Manage the entire client, allow/block chats, snooze replies, or change persona instructions straight from your **Telegram Saved Messages**.
- **Dual Deployment**: Run locally on your Arch Linux laptop or 24/7 in a lightweight Docker container on a Linux VPS.

---

## 2. Differences: Telegram Bot vs. Personal MTProto Account

| Feature | Telegram Bot (`@BotFather`) | Personal MTProto Client (This Project) |
| :--- | :--- | :--- |
| **Account Identity** | Bot badge (`@sample_bot`) | **Your real personal Telegram account** |
| **Authentication** | Bot token (`123456:ABC...`) | **MTProto Session** via API ID + API Hash + Phone Login |
| **Chat Access** | Only where bot is explicitly invited | **Any private conversation or group you participate in** |
| **Message Presentation** | Marked as "bot" | **Appears exactly like normal messages typed by you** |
| **Privacy Terms** | Bot API Terms | **Official Telegram MTProto Fair Use** |

---

## 3. Architecture & Folder Structure

Both local and cloud setups share the exact same core code inside `app/`:

```text
telegram-chat-automation/
├── app/                      # Shared Core Logic
│   ├── __init__.py
│   ├── banner.py             # Professional startup banner & copyright attribution
│   ├── main.py               # Main runtime entrypoint & Docker health check CLI
│   ├── config.py             # Configuration loader & bound validator
│   ├── telegram_client.py    # Telethon MTProto client lifecycle & reconnect backoff
│   ├── session_manager.py    # Local file session (0600) & Cloud StringSession generator
│   ├── event_handlers.py     # Dispatches messages & Saved Messages commands
│   ├── message_filter.py     # Scam link filter, service message drop, group mention guard
│   ├── reply_manager.py      # Draft, Approval, and Auto-reply orchestrator
│   ├── safety_manager.py     # Cooldowns, dedup, OTP guard, emergency stop, timed pause
│   ├── privacy_manager.py    # Dynamic chat allowlist & user exclusions
│   ├── logger.py             # Structured logging with automatic secret redaction
│   ├── health.py             # Heartbeat monitor & container health check
│   │
│   ├── ai/                   # AI Subsystem
│   │   ├── __init__.py
│   │   ├── provider.py       # Google Gemini (gemini-3.5-flash with fallback), OpenAI, Local
│   │   ├── prompt_manager.py # Anti-AI sanitizer, language matching, & human persona
│   │   └── reply_generator.py# Coordinates prompt assembly and draft generation
│   │
│   └── storage/              # SQLite Persistent Storage
│       ├── __init__.py
│       └── database.py       # Database for approvals, dedup, dynamic chats & keyword rules
│
├── local/                    # Local Laptop Deployment Environment
│   ├── setup.sh              # Virtualenv creation, dependency installation, .env setup
│   ├── install.sh            # Reinstalls requirements
│   ├── authenticate.sh       # Interactive terminal login & StringSession exporter
│   ├── start.sh              # Starts local client
│   ├── test.sh               # Runs pytest test suite
│   ├── .env.example          # Local environment template
│   └── README.md             # Dedicated Local Deployment Guide
│
├── cloud/                    # 24/7 Cloud VPS Deployment Environment
│   ├── Dockerfile            # Secure non-root container image (Python slim, appuser)
│   ├── compose.yaml          # Docker Compose with persistent volume & restart policy
│   ├── .dockerignore         # Docker context exclusions
│   ├── .env.example          # Cloud environment template (StringSession)
│   ├── entrypoint.sh         # Non-root permission checks & startup
│   ├── healthcheck.sh        # Self-contained container health checker
│   ├── deploy.sh             # Cloud build and launch helper
│   ├── system_prompt.txt     # Cloud bundled AI persona prompt
│   └── README.md             # Dedicated Cloud VPS Deployment Guide
│
├── scripts/                  # Utilities
│   ├── authenticate.py       # Interactive phone/code/2FA login script
│   ├── check_connection.py   # Non-destructive account verification
│   └── generate_session.py   # StringSession exporter for cloud deployment
│
├── tests/                    # 21 Automated Unit Tests (pytest)
├── system_prompt.txt         # Live editable AI persona instructions
├── requirements.txt
├── pyproject.toml
├── .gitignore
├── .dockerignore
└── README.md
```

---

## 4. Step-by-Step Beginner Setup Guide

Follow these steps sequentially to set up and run the client:

### Step 4.1: Getting Telegram API Credentials (my.telegram.org)
1. Open your browser and go to: **[https://my.telegram.org](https://my.telegram.org)**.
2. Enter your phone number (with country code, e.g. `+91...` or `+1...`) and log in using the code sent to your Telegram app.
3. Click on **API development tools**.
4. Fill in the short form:
   - **App title**: Any name (e.g. `MyPersonalClient`)
   - **Short name**: Any single word (e.g. `myclient`)
   - **Platform**: Desktop / Other
5. Click **Create application**.
6. You will see:
   - **`api_id`**: A numeric ID (e.g., `34656768`)
   - **`api_hash`**: A 32-character hexadecimal string (e.g., `7c7077f000e5a2da...`)
   *(Keep these private; do not share them).*

---

### Step 4.2: Getting a Free Google Gemini API Key
1. Go to **[Google AI Studio](https://aistudio.google.com/app/apikey)**.
2. Sign in with your Google account.
3. Click **Create API key**.
4. Copy your key (starts with `AIzaSy...` or `AQ...`).

---

### Step 4.3: Local Installation & Configuration
Open your terminal on your laptop:
```bash
# 1. Clone or navigate to the project directory
cd telegram-chat-automation

# 2. Run the automated local setup script
./local/setup.sh
```
This script automatically:
- Checks for Python 3.10+
- Creates an isolated virtual environment in `.venv/`
- Installs all required packages (`telethon`, `python-dotenv`, `pytest`)
- Creates a private `.env` file with restrictive `0600` permissions

Now open `.env` in an editor:
```bash
nano .env
```
Fill in your credentials:
```env
# Paste your credentials from my.telegram.org
TG_API_ID=34656768
TG_API_HASH=7c7077f000e5a2da382562c27881a5fc

# Enable Google Gemini
AI_ENABLED=true
AI_PROVIDER=gemini
AI_API_KEY=your_gemini_api_key_here
AI_MODEL=gemini-3.5-flash

# Set automation mode
REPLY_MODE=restricted_auto
AUTO_AUTHORIZE=true

# Add allowed chat IDs (leave blank for now if you don't know them yet)
ALLOWED_PRIVATE_CHATS=
ALLOWED_GROUPS=
```
Save and exit (`Ctrl+O`, then `Enter`, then `Ctrl+X`).

---

### Step 4.4: First-Time Phone & 2FA Authentication
Run the interactive login script:
```bash
./local/authenticate.sh
```
1. Enter your phone number with country code (e.g. `+1234567890`).
2. Enter the 5-digit verification code sent to your Telegram app.
3. If Two-Step Verification (2FA) is enabled, enter your password.
4. The script verifies your account, locks session file permissions (`0600`), and prints your **Cloud StringSession (`TG_SESSION_STRING`)** (save this if you plan to deploy to a VPS later).

---

### Step 4.5: Finding & Setting Chat IDs
**How to find someone's Chat ID:**
- **Method 1 (Automatic)**: Just start the client! When anyone messages you, the terminal will print:
  ```text
  [CHAT DETECTED] Received message from Chat ID: 123456789. To allow replies, add 123456789 to ALLOWED_PRIVATE_CHATS in .env
  ```
- **Method 2 (From Telegram)**: Once the client is running, you don't even have to edit `.env`! Simply send `/allowchat 123456789` in your **Saved Messages**!
- **Method 3**: Forward any message from the user to `@userinfobot` in Telegram.
- **For Groups**: Group IDs are negative numbers (e.g. `-1001234567890`).

---

### Step 4.6: Running the Client
Start the client:
```bash
./local/start.sh
```
When it starts, check your Telegram app under **Saved Messages**. You will receive an immediate startup notification with your active status and command guide!

---

## 5. Telegram Saved Messages Control Center (Interactive Commands)

You can control and customize everything by sending commands directly to your **Saved Messages** (chat with yourself) from your phone:

| Command | Action | Example |
| :--- | :--- | :--- |
| **`/status`** | Shows active health, identity name, pause timer, and reply mode | `/status` |
| **`/chats`** | Lists all allowlisted private contacts and groups | `/chats` |
| **`/allowchat <id>`** | Adds a contact or group ID to allowlist instantly | `/allowchat 123456789` |
| **`/removechat <id>`**| Removes a chat from the allowlist | `/removechat 123456789` |
| **`/blockchat <id>`** | Blacklists a chat completely | `/blockchat 987654321` |
| **`/pause <time>`** | Snoozes auto-replies for a set duration | `/pause 2h` or `/pause 30m` |
| **`/resume`** | Clears pause/stop and resumes normal listening | `/resume` |
| **`/stop`** | **Emergency kill switch**: immediately halts all outgoing messages | `/stop` |
| **`/name <name>`** | Sets your display name for the AI persona | `/name Kaif` |
| **`/prompt`** | Views active system instructions on your phone | `/prompt` |
| **`/setprompt <text>`**| Updates the AI prompt on the fly without touching code | `/setprompt You are chill and brief.` |
| **`/auto on` / `off`** | Authorizes or revokes automated sending mode | `/auto on` |
| **`/pending`** | Lists drafts waiting for manual review (in approval mode) | `/pending` |
| **`/approve <id>`** | Approves and sends draft `#<id>` | `/approve 1` |
| **`/reject <id>`** | Discards draft `#<id>` | `/reject 1` |
| **`/help`** | Shows the full interactive command guide | `/help` |

---

## 6. Setting Custom Keyword Trigger Rules From Telegram

You can set custom instant auto-replies for specific keywords without waiting for AI generation:

### Adding a Keyword Trigger
Send to your **Saved Messages**:
```text
/addrule pricing => Our packages are being updated, will send details shortly!
```
Or for another keyword:
```text
/addrule portfolio => Check out my github profile at github.com/mkr-infinity
```

### Viewing Active Rules
Send:
```text
/rules
```
It returns all active keyword triggers.

### Deleting a Rule
Send:
```text
/delrule pricing
```

Whenever an incoming message contains that keyword, the client replies with your exact chosen text immediately!

---

## 7. Group Chat Automation & Mention Filters

Running automation in high-volume groups requires strict spam protection:

### Group Mention Filter (`/mentiononly`)
- **`/mentiononly on` (Default ON)**: In groups, the client **only** replies when someone explicitly mentions your `@username` or directly replies to one of your messages. It will never spam the group when other members are talking among themselves.
- **`/mentiononly off`**: Allows replying to every message in allowlisted groups (recommended only for small private discussion groups).

### Adding a Group
1. Find the group ID (always negative, e.g. `-1001234567890`).
2. Send to Saved Messages:
   ```text
   /allowchat -1001234567890
   ```

---

## 8. Anti-Scam & Link Protection System

- **Scam Link Detection**: Automatically detects and drops scammer messages containing:
  - Private channel join links (`t.me/+...`, `t.me/joinchat/...`).
  - Crypto traps (`airdrop`, `free usdt`, `crypto bonus`, `claim reward`, `investment opportunity`).
  - Suspicious URL shorteners (`bit.ly`, `tinyurl`, `cutt.ly`, `rb.gy`, etc.).
- **Zero Outgoing Links**: The AI is strictly instructed and post-processed by a hard-coded regex sanitizer that strips any URLs before messages are dispatched.

---

## 9. Human Persona & Language Matching (Hindi + English)

Configured in [`system_prompt.txt`](file:///home/kaif/Downloads/Projects/telegram-chat-automation/system_prompt.txt):
- **Hindi / Hinglish**: If someone texts in Hindi or Hinglish, the AI replies naturally:
  - *"bhai kaisa hai?"* ➜ `sab badhiya bhai, tu bata`
  - *"aaj sham ko milte hai kya?"* ➜ `haan bhai, sham ko milte hain`
- **English**: If someone texts in English:
  - *"Hey bro what are you doing?"* ➜ `not much, just chilling! what's up with you?`
- **Anti-AI Human Alibi**:
  - *"are you an ai?"* ➜ `lol what? no bro, it's me haha`
  - *"which model are you using?"* ➜ `model? mai toh bas phone se type kar raha hu bhai 😂`

---

## 10. Local Deployment Guide (Reference)

For dedicated instructions on running the client locally on an Arch Linux or standard Linux laptop, see:
👉 **[`local/README.md`](file:///home/kaif/Downloads/Projects/telegram-chat-automation/local/README.md)**

---

## 11. Cloud VPS 24/7 Deployment Guide (Reference)

For step-by-step instructions on deploying the client to a Linux VPS using Docker Compose (so it stays online 24/7 without your laptop), see:
👉 **[`cloud/README.md`](file:///home/kaif/Downloads/Projects/telegram-chat-automation/cloud/README.md)**

---

## 12. Emergency Kill Switch & Safety Guards

If you ever need to stop the client immediately:
- **From your Phone**: Send `/stop` in **Saved Messages**. All automated replies halt instantly.
- **From Terminal (Local)**: Press `Ctrl+C`.
- **From VPS (Cloud)**: Run `docker compose down` inside `cloud/`.
- **Compromised Session**: Open Telegram on your phone ➜ **Settings ➜ Devices ➜ Terminate Session**.

---

## 13. Troubleshooting & FAQ

- **Error: `HTTP Error 404: Not Found` on Gemini API**
  - Ensure `AI_MODEL=gemini-3.5-flash` in `.env`. Older models like `gemini-1.5-flash` are deprecated by Google.
- **Error: `Missing required configuration: TG_API_ID`**
  - Open `.env` and fill in your actual numeric API ID from my.telegram.org.
- **Running Tests**:
  - Run `./local/test.sh` to execute all 21 unit tests.

---

## 14. License & Attribution

```text
Author:     Mohammad Kaif Raja (mkr-infinity)
Telegram:   @mkr_infinity (https://t.me/mkr_infinity)
Instagram:  @mkr_infinity (https://instagram.com/mkr_infinity)
Copyright:  Copyright (c) Mohammad Kaif Raja. All Rights Reserved.
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
~  If you modify, redistribute, or sell anything made from my things without my         ~
~  permission, it is strictly prohibited. Free to use for personal use.                 ~
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unauthorized removal of attribution is strictly prohibited.
```
Licensed under the [Proprietary Source-Available License](LICENSE). Free for personal use; redistribution and modification without permission are strictly prohibited.
