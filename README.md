# Telegram Chat Automation v1.0

```text
========================================================================================
  Telegram Chat Automation v1.0
  ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

  A production-ready automation tool for automating whole telegram messages from
  bot-bot, account-bot, groups messages etc all from your main account.

  Author:     Mohammad Kaif Raja (mkr-infinity)
  Telegram:   @mkr_infinity (https://t.me/mkr_infinity)
  Instagram:  @mkr_infinity (https://instagram.com/mkr_infinity)
  Copyright:  Copyright (c) Mohammad Kaif Raja. All Rights Reserved.
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
~  Unauthorized modification, redistribution, or commercial sale of this software       ~
~  is strictly prohibited without prior written permission. Personal use permitted.     ~
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
  Unauthorized removal of attribution is strictly prohibited.
========================================================================================
```

---

## 📑 Complete Table of Contents
1. [Overview & Core Capabilities](#1-overview--core-capabilities)
2. [Differences: Telegram Bot vs. Personal MTProto Account](#2-differences-telegram-bot-vs-personal-mtproto-account)
3. [Unified Repository Architecture](#3-unified-repository-architecture)
4. [Universal Quick Start & System Detection](#4-universal-quick-start--system-detection)
   - [Linux & macOS (Auto-detects Arch, Debian, Ubuntu, Fedora, Alpine)](#41-linux--macos-auto-detects-arch-debian-ubuntu-fedora-alpine)
   - [Remote Server / VPS (Headless SSH)](#42-remote-server--vps-headless-ssh)
   - [Windows (PowerShell or Universal Python Runner)](#43-windows-powershell-or-universal-python-runner)
   - [Docker 24/7 Background Deployment](#44-docker-247-background-deployment)
5. [Step-by-Step Beginner Credentials Setup](#5-step-by-step-beginner-credentials-setup)
   - [Step 5.1: Getting Telegram API Credentials (my.telegram.org)](#step-51-getting-telegram-api-credentials-mytelegramorg)
   - [Step 5.2: Getting a Free Google Gemini API Key](#step-52-getting-a-free-google-gemini-api-key)
   - [Step 5.3: First-Time Phone & 2FA Authentication](#step-53-first-time-phone--2fa-authentication)
   - [Step 5.4: Finding & Setting Chat IDs](#step-54-finding--setting-chat-ids)
6. [Telegram Saved Messages Control Center (Interactive Commands)](#6-telegram-saved-messages-control-center-interactive-commands)
7. [Setting Custom Keyword Trigger Rules From Telegram](#7-setting-custom-keyword-trigger-rules-from-telegram)
8. [Group Chat Automation & Mention Filters](#8-group-chat-automation--mention-filters)
9. [Anti-Scam & Link Protection System](#9-anti-scam--link-protection-system)
10. [Human Persona & Language Matching (Hindi + English)](#10-human-persona--language-matching-hindi--english)
11. [Emergency Kill Switch & Safety Guards](#11-emergency-kill-switch--safety-guards)
12. [Testing & Verification](#12-testing--verification)
13. [License & Legal Notice](#13-license--legal-notice)

---

## 1. Overview & Core Capabilities

**Telegram Chat Automation** is a production-grade Telegram automation client built with **Python 3**, **Telethon (MTProto)**, and **Google Gemini AI**.

Unlike third-party bots, this application connects directly as your **real personal Telegram account**:
- **Natural Texting Tone**: Speaks casually like a human, never like a corporate AI chatbot.
- **Bilingual Hindi & English**: Replies in Hindi/Hinglish to Hindi messages, and in English to English messages.
- **Human Alibi (Zero AI Disclosure)**: If asked *"are you an AI?"* or *"what model is this?"*, it laughs it off as a human typing on their phone.
- **Anti-Scam & Link Blocker**: Detects and drops scam links, crypto baits, and spam channel invites. AI is strictly barred from sending outgoing links.
- **Custom Keyword Triggers**: Set instant replies for specific keywords directly from Telegram (e.g. `/addrule pricing => Details sent shortly`).
- **Remote Control via Saved Messages**: Change modes (`/auto on`), pause (`/pause 2h`), allow chats (`/allowchat <id>`), or update prompt instructions directly from your phone.
- **Universal Multi-Platform Setup**: Single unified codebase that automatically adapts to Arch Linux, Debian/Ubuntu, Fedora, Alpine, macOS, Windows, or 24/7 cloud servers.

---

## 2. Differences: Telegram Bot vs. Personal MTProto Account

| Feature | Telegram Bot (`@BotFather`) | Personal MTProto Client (This Tool) |
| :--- | :--- | :--- |
| **Account Identity** | Bot badge (`@sample_bot`) | **Your real personal Telegram account** |
| **Authentication** | Bot token (`123456:ABC...`) | **MTProto Session** via API ID + API Hash + Phone Login |
| **Chat Access** | Only where bot is explicitly invited | **Any private conversation or group you participate in** |
| **Message Presentation** | Marked as "bot" | **Appears exactly like normal messages typed by you** |

---

## 3. Unified Repository Architecture

All scripts and configuration live cleanly in the root directory—no split `local/` or `cloud/` subdirectories:

```text
telegram-chat-automation/
├── app/                      # Application Logic
│   ├── banner.py             # Startup banner & author attribution
│   ├── main.py               # Main runtime entrypoint & Docker healthcheck CLI
│   ├── config.py             # Environment loader & bound validator
│   ├── telegram_client.py    # Telethon MTProto client lifecycle & reconnect backoff
│   ├── session_manager.py    # File session (0600) & StringSession handler
│   ├── event_handlers.py     # Dispatches messages & Saved Messages commands
│   ├── message_filter.py     # Scam link filter, service message drop, group mention guard
│   ├── reply_manager.py      # Draft, Approval, and Auto-reply orchestrator
│   ├── safety_manager.py     # Cooldowns, dedup, OTP guard, emergency stop, timed pause
│   ├── privacy_manager.py    # Dynamic chat allowlist & user exclusions
│   ├── logger.py             # Redacting logger masking hashes, keys, and tokens
│   ├── health.py             # Heartbeat monitor & health checks
│   │
│   ├── ai/                   # AI Subsystem
│   │   ├── provider.py       # Google Gemini (gemini-3.5-flash) with stdlib fallback
│   │   ├── prompt_manager.py # Anti-AI sanitizer, language matching, & human persona
│   │   └── reply_generator.py# Assembly of prompt context & draft generation
│   │
│   └── storage/              # SQLite Persistent Storage
│       └── database.py       # Database for approvals, dedup, dynamic chats & keyword rules
│
├── scripts/                  # Helper Utilities
│   ├── authenticate.py       # Interactive phone/code/2FA login script
│   ├── check_connection.py   # Non-destructive MTProto connection tester
│   └── generate_session.py   # Telethon StringSession exporter
│
├── setup.sh                  # Universal system-detecting setup script (Arch, Debian, macOS, Server)
├── setup.ps1                 # Native Windows PowerShell setup script
├── run.py                    # Universal cross-platform Python runner (Windows, Linux, macOS, Server)
├── start.sh                  # Starts client locally or on server
├── authenticate.sh           # Interactive terminal authentication helper
├── test.sh                   # Runs automated pytest unit test suite
├── Dockerfile                # Hardened non-root container image for 24/7 servers
├── compose.yaml              # Docker Compose configuration with persistent volume
├── entrypoint.sh             # Container entrypoint with permission hardening
├── healthcheck.sh            # Container healthcheck runner
├── system_prompt.txt         # Live editable AI persona prompt
├── requirements.txt          # Python dependencies
├── .env.example              # Unified environment configuration template
├── LICENSE                   # Proprietary Source-Available License
└── README.md
```

---

## 4. Universal Quick Start & System Detection

### 4.1 Linux & macOS (Auto-detects Arch, Debian, Ubuntu, Fedora, Alpine)
Open your terminal and run:
```bash
./setup.sh
```
What `setup.sh` does automatically:
1. Detects your specific Linux distribution (`pacman`, `apt`, `dnf`, `apk`, `brew`).
2. Confirms Python 3.10+ is installed (or tells you the exact one-line command to install it).
3. Creates a Python virtual environment in `.venv/` and installs dependencies.
4. Initializes `.env` with secure `0600` permissions.
5. Sets up the secure `data/` directory (`0700`).

---

### 4.2 Remote Server / VPS (Headless SSH)
If you are logged into a server over SSH:
1. Run `./setup.sh` on the server.
2. Authenticate directly inside the SSH terminal:
   ```bash
   ./authenticate.sh
   ```
   Enter your phone number and the Telegram verification code when prompted.
3. Start the client:
   ```bash
   ./start.sh
   ```
   *(Tip: use `tmux` or `systemd` to keep it running after disconnecting from SSH).*

---

### 4.3 Windows (PowerShell or Universal Python Runner)

**Option A (PowerShell):**
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\setup.ps1
```

**Option B (Universal Python Runner - Works Everywhere):**
```bash
# Setup
python run.py --setup

# Authenticate with Telegram
python run.py --auth

# Start the client
python run.py
```

---

### 4.4 Docker 24/7 Background Deployment
To run continuously 24/7 on a VPS or home server using Docker:
1. Complete authentication locally or on the server using `./authenticate.sh`.
2. Start the container:
   ```bash
   docker compose up -d --build
   ```
3. View logs:
   ```bash
   docker compose logs -f
   ```

---

## 5. Step-by-Step Beginner Credentials Setup

### Step 5.1: Getting Telegram API Credentials (my.telegram.org)
1. Go to **[https://my.telegram.org](https://my.telegram.org)** in your web browser.
2. Enter your phone number with country code (e.g. `+91...` or `+1...`).
3. Enter the confirmation code sent to your Telegram app.
4. Click **API development tools**.
5. Fill in the form:
   - **App title**: `TelegramAutomation`
   - **Short name**: `teleauto`
   - **Platform**: Desktop / Other
6. Click **Create application**.
7. Copy your **`api_id`** (numeric) and **`api_hash`** (32-character string).

---

### Step 5.2: Getting a Free Google Gemini API Key
1. Visit **[Google AI Studio](https://aistudio.google.com/app/apikey)**.
2. Sign in with your Google account.
3. Click **Create API key**.
4. Copy your key and add it to `.env`:
   ```env
   AI_ENABLED=true
   AI_PROVIDER=gemini
   AI_API_KEY=AIzaSy...
   AI_MODEL=gemini-3.5-flash
   ```

---

### Step 5.3: First-Time Phone & 2FA Authentication
Run:
```bash
./authenticate.sh
```
1. Enter your phone number with country code (e.g. `+911234567890`).
2. Enter the 5-digit verification code sent to your Telegram app.
3. If Two-Step Verification (2FA) is enabled, enter your password securely.
4. The script logs in, generates the MTProto session, and prints your session details.

---

### Step 5.4: Finding & Setting Chat IDs
- **Automatic Detection**: When anyone messages you, the terminal logs print:
  ```text
  [CHAT DETECTED] Received message from Chat ID: 123456789. To allow replies, add to ALLOWED_PRIVATE_CHATS or send /allowchat 123456789 in Saved Messages.
  ```
- **Allowing Directly from Phone**: Send `/allowchat 123456789` in your **Saved Messages** chat.
- **For Groups**: Group IDs are negative numbers (e.g. `-1001234567890`).

---

## 6. Telegram Saved Messages Control Center (Interactive Commands)

Control your client on the fly by sending commands to your **Saved Messages**:

| Command | Action | Example |
| :--- | :--- | :--- |
| **`/status`** | Shows active status, health, reply mode, and identity | `/status` |
| **`/chats`** | Lists allowlisted private chats and groups | `/chats` |
| **`/allowchat <id>`** | Adds a chat to allowlist immediately | `/allowchat 123456789` |
| **`/removechat <id>`**| Removes a chat from allowlist | `/removechat 123456789` |
| **`/blockchat <id>`** | Blocks a chat from receiving automated replies | `/blockchat 987654321` |
| **`/pause <duration>`**| Snoozes replies for a duration | `/pause 2h` or `/pause 45m` |
| **`/resume`** | Resumes replies from pause or stop | `/resume` |
| **`/stop`** | **Emergency kill switch**: immediately halts all outgoing messages | `/stop` |
| **`/name <name>`** | Updates owner name in the AI system prompt | `/name Kaif` |
| **`/prompt`** | Displays active AI prompt instructions | `/prompt` |
| **`/setprompt <text>`**| Updates AI prompt instructions on the fly | `/setprompt Be chill and brief.` |
| **`/auto on` / `off`** | Authorizes or halts automated sending mode | `/auto on` |
| **`/help`** | Shows the complete interactive command guide | `/help` |

---

## 7. Setting Custom Keyword Trigger Rules From Telegram

Set instant custom responses that trigger immediately whenever an incoming message contains specific keywords:

### Adding a Rule
Send to **Saved Messages**:
```text
/addrule pricing => Our packages are being updated, will share details shortly!
```

### Viewing All Active Rules
Send:
```text
/rules
```

### Deleting a Rule
Send:
```text
/delrule pricing
```

---

## 8. Group Chat Automation & Mention Filters

- **`/mentiononly on` (Default)**: In groups, the client **only** replies when someone explicitly mentions your `@username` or replies directly to your message. It will never spam the group when members talk to each other.
- **`/mentiononly off`**: Replies to all messages in allowlisted groups.

---

## 9. Anti-Scam & Link Protection System

- **Scam Detection**: Automatically drops messages containing suspicious crypto baits, Telegram channel invite links (`t.me/+...`), or URL shorteners.
- **Zero Outgoing Links**: AI replies are sanitized by a hard-coded regex engine that strips any URLs before sending.

---

## 10. Human Persona & Language Matching (Hindi + English)

Configured in [`system_prompt.txt`](file:///home/kaif/Downloads/Projects/telegram-chat-automation/system_prompt.txt):
- **Hindi / Hinglish**: *"bhai kaisa hai?"* ➜ `sab badhiya bhai, tu bata`
- **English**: *"Hey bro what are you doing?"* ➜ `not much, just chilling! what's up with you?`
- **Anti-AI Alibi**:
  - *"are you an ai?"* ➜ `lol what? no bro, it's me haha`
  - *"which model are you using?"* ➜ `model? mai toh bas phone se type kar raha hu bhai 😂`

---

## 11. Emergency Kill Switch & Safety Guards

- **Emergency Stop**: Send `/stop` in Saved Messages to immediately disable all outgoing messages.
- **Timed Pause**: Send `/pause 1h` to pause automation for 1 hour.
- **Rate Limits**: Global (30s) and per-chat (60s) cooldowns prevent spam or Telegram flood bans.
- **Sensitive Content Guard**: Drops messages containing passwords, OTPs, seed phrases, or credit card terms.

---

## 12. Testing & Verification

Run the test suite:
```bash
./test.sh
```
Or using the universal runner:
```bash
python run.py --test
```
*(All 21 unit tests verify privacy, safety, cooldowns, AI generation, and session management).*

---

## 13. License & Legal Notice

```text
Author:     Mohammad Kaif Raja (mkr-infinity)
Telegram:   @mkr_infinity (https://t.me/mkr_infinity)
Instagram:  @mkr_infinity (https://instagram.com/mkr_infinity)
Copyright:  Copyright (c) Mohammad Kaif Raja. All Rights Reserved.
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
~  Unauthorized modification, redistribution, or commercial sale of this software       ~
~  is strictly prohibited without prior written permission. Personal use permitted.     ~
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unauthorized removal of attribution is strictly prohibited.
```

Licensed under the [Proprietary Source-Available License](LICENSE). Free for personal use; redistribution and modification without permission are strictly prohibited.
