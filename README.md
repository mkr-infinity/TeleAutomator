# TeleAutomator - Telegram Chat Automation v1.0

```text
========================================================================================
  TeleAutomator - Telegram Chat Automation v1.0
  ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
  "Your Telegram account, powered by AI. 🤖"

  Production-grade Telegram user-account automation with Google Gemini AI,
  human alibi persona, custom keyword triggers, and zero-spam safety guards.

  Repository: https://github.com/mkr-infinity/TeleAutomator
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

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![MTProto Telethon](https://img.shields.io/badge/protocol-MTProto%20Telethon-informational.svg)](https://github.com/LonamiWebs/Telethon)
[![Google Gemini](https://img.shields.io/badge/AI-Google%20Gemini%203.5--Flash-orange.svg)](https://aistudio.google.com/)
[![License](https://img.shields.io/badge/license-Source--Available-red.svg)](LICENSE)
[![Tests Passing](https://img.shields.io/badge/tests-28%2F28%20passed-brightgreen.svg)](test.sh)

---

## 📑 Complete Table of Contents
1. [Project Overview & Core Purpose](#1-project-overview--core-purpose)
2. [Differences: Telegram Bot vs. Personal MTProto Client](#2-differences-telegram-bot-vs-personal-mtproto-client)
3. [Features](#3-features)
4. [How It Works & Message Lifecycle](#4-how-it-works--message-lifecycle)
5. [Architecture Overview & Technology Stack](#5-architecture-overview--technology-stack)
6. [Multi-System Installation & Setup](#6-multi-system-installation--setup)
   - [Arch Linux & Manjaro (Native Local Setup)](#61-arch-linux--manjaro-native-local-setup)
   - [Debian, Ubuntu & Linux Mint](#62-debian-ubuntu--linux-mint)
   - [Windows (PowerShell & Universal Runner)](#63-windows-powershell--universal-runner)
   - [macOS](#64-macos)
   - [24/7 Cloud VPS & Docker Server Deployment](#65-247-cloud-vps--docker-server-deployment)
7. [Step-by-Step Beginner Credentials Setup](#7-step-by-step-beginner-credentials-setup)
   - [Step 7.1: Telegram API Credentials (my.telegram.org)](#step-71-telegram-api-credentials-mytelegramorg)
   - [Step 7.2: Free Google Gemini API Key](#step-72-free-google-gemini-api-key)
   - [Step 7.3: First-Time Phone & 2FA Authentication](#step-73-first-time-phone--2fa-authentication)
   - [Step 7.4: Finding & Authorizing Chat IDs](#step-74-finding--authorizing-chat-ids)
8. [Automation Modes & Control](#8-automation-modes--control)
   - [Draft-Only Mode (CLI & Telegram Controlled)](#81-draft-only-mode-cli--telegram-controlled)
   - [Approval-Required Mode](#82-approval-required-mode)
   - [Restricted Automation Mode](#83-restricted-automation-mode)
9. [Configurable Response Styles](#9-configurable-response-styles)
10. [AI System Prompt Customization, Typing Delay & Tone Matching](#10-ai-system-prompt-customization-typing-delay--tone-matching)
    - [10.1 Where & How to Modify the System Prompt](#101-where--how-to-modify-the-system-prompt)
    - [10.2 Adaptive Randomized Human Delay (5 to 60 Seconds)](#102-adaptive-randomized-human-delay-5-to-60-seconds)
    - [10.3 Exact Tone, Slang & Language Matching (Hindi, Hinglish, English)](#103-exact-tone-slang--language-matching-hindi-hinglish-english)
11. [Saved Messages Remote Control Center (Commands Reference)](#11-saved-messages-remote-control-center-commands-reference)
12. [Custom Keyword Triggers](#12-custom-keyword-triggers)
13. [Group Chat Automation & Mention Safety](#13-group-chat-automation--mention-safety)
14. [Security, Privacy & Anti-Scam Protection](#14-security-privacy--anti-scam-protection)
15. [Testing & Verification](#15-testing--verification)
16. [Troubleshooting & FAQ](#16-troubleshooting--faq)
17. [Roadmap](#17-roadmap)
18. [Contribution Guidelines](#18-contribution-guidelines)
19. [License & Attribution](#19-license--attribution)

---

## 1. Project Overview & Core Purpose

> **"Your Telegram account, powered by AI. 🤖"**

**TeleAutomator** is an enterprise-grade Telegram automation platform built with **Python 3**, **Telethon (MTProto)**, and **Google Gemini AI**.

Unlike basic third-party bot scripts created via `@BotFather`, TeleAutomator operates directly on your **real personal Telegram account**. It listens to incoming messages, evaluates privacy and anti-scam rules, understands conversation history, crafts natural, context-aware human replies, and gives you remote control over every conversation straight from your Telegram **Saved Messages** or local terminal.

---

## 2. Differences: Telegram Bot vs. Personal MTProto Client

| Feature | Telegram Bot (`@BotFather`) | TeleAutomator Personal MTProto Client |
| :--- | :--- | :--- |
| **Account Identity** | Bot badge (`@example_bot`) | **Your real personal Telegram account** |
| **Authentication** | Bot Token (`123456:ABC...`) | **MTProto Session** via API ID + API Hash + Phone Login |
| **Chat Reach** | Only where explicitly added or DM'd | **Any conversation or group you already participate in** |
| **Message Presentation** | Displayed as bot | **Appears exactly like normal messages typed by you** |
| **Bot-to-Bot Interactions**| Telegram forbids bot-to-bot chats | **Fully capable of interacting with other Telegram bots** |
| **Privacy Terms** | Bot API Privacy Boundary | **Telegram MTProto Personal Fair Use** |

---

## 3. Features

- **Context-Aware AI Generation**: Understands the conversational flow, considering replied-to messages and recent chat history when authorized.
- **Exact Tone & Slang Matching**: Dynamically matches the sender's energy, brevity, humor, and casual slang without sounding like a robotic assistant.
- **Bilingual Hindi, Hinglish & English Mirroring**: Replies in authentic Hinglish or pure Devanagari Hindi when addressed in Hindi, and natural casual English when spoken to in English.
- **Adaptive Randomized Human Delay (5 to 60s)**: Emulates real human typing and reading pauses (5-25s in group chats, 10-60s in private DMs), dynamically adapting to conversation pace and message complexity.
- **Dynamic System Prompt Customization**: Modify the AI persona anytime via `system_prompt.txt` in the root folder or remotely via `/prompt` and `/setprompt` in Saved Messages.
- **Human Alibi Persona (Zero AI Disclosure)**: If asked *"are you an AI?"* or *"what model is this?"*, it laughs it off naturally like a human texting on their phone.
- **Configurable Response Styles**: Switch on the fly between `casual`, `concise`, `formal`, or `humorous` response styles.
- **Draft-Only Mode**: Set via CLI (`--draft`, `--mode draft`) or from Telegram (`/mode draft`) to log suggested drafts without sending.
- **Human Approval Workflow**: Review suggestions in your Saved Messages; dispatch with `/approve <id>` or discard with `/reject <id>`.
- **Instant Custom Keyword Rules**: Set exact responses for specific words from Telegram (e.g., `/addrule pricing => We'll share details shortly`).
- **Anti-Scam & Phishing Blocker**: Drops scam links, crypto airdrop baits, and channel invite traps (`t.me/+...`).
- **Zero Outgoing Links**: Regex post-processing bars the AI from ever outputting URLs or links.
- **Zero Group/Peer Error Leaks**: If an AI provider fails, rate limits, or experiences an error, no fallback text or error messages are EVER sent to groups or peer chats. All error and issue alerts are routed strictly to your private Telegram Saved Messages.
- **Group Mention Filter**: In high-volume groups, only responds when your `@username` is tagged or your message is replied to.
- **Emergency Kill Switch**: Send `/stop` in Saved Messages to immediately halt all outgoing actions.
- **Multi-Platform Universal Setup**: Automatically detects Arch Linux, Debian, Ubuntu, Fedora, Alpine, macOS, Windows, and headless servers.

---

## 4. How It Works & Message Lifecycle

```
[ Incoming Message Event ]
            │
            ▼
[ Message Filter & Guard ] ──(Scam Link / Sensitive OTP / Outgoing / Ignored)──► [ DROP & LOG ]
            │
            ├─► Matches Custom Keyword Rule? ──► Use Instant Keyword Reply
            │
            └─► Eligible for AI?
                     │
                     ▼
       [ Extract Conversation Context ]
       (Replied-to message & history)
                     │
                     ▼
       [ AI Reply Generator (Gemini) ]
       (Anti-AI Sanitizer & Link Stripper)
                     │
                     ▼
        ┌────────────┴────────────┐
        ▼                         ▼                         ▼
 [ Mode: Draft ]        [ Mode: Approval ]         [ Mode: Restricted Auto ]
   Logs draft to          Sends draft to             Verifies limits & cooldown,
   terminal & DB          Saved Messages for         waits adaptive delay (5-60s)
   (Never sends)          manual /approve <id>       with typing, then sends via MTProto
```

---

## 5. Architecture Overview & Technology Stack

TeleAutomator is built following modular, asynchronous software engineering principles:

```text
teleautomator/
├── app/                      # Application Logic
│   ├── banner.py             # Startup banner, tagline, repo URL & author credits
│   ├── main.py               # Application entrypoint & CLI argument router
│   ├── config.py             # Environment variable loader & bound validator
│   ├── telegram_client.py    # Telethon client lifecycle, reconnect backoff & onboarding
│   ├── session_manager.py    # File sessions (0600) & StringSession support
│   ├── event_handlers.py     # Telegram message event router & command dispatcher
│   ├── message_filter.py     # Scam link filter, bot command drop, group mention guard
│   ├── reply_manager.py      # Draft, Approval, and Auto-reply orchestrator & commands
│   ├── safety_manager.py     # Cooldowns, dedup, OTP filter, pause timer & emergency stop
│   ├── privacy_manager.py    # Chat allowlists, user exclusions & PII text scrubbing
│   ├── logger.py             # Redacting logger masking hashes, keys, and tokens
│   ├── health.py             # Heartbeat monitor & container health check CLI
│   │
│   ├── ai/                   # AI Subsystem
│   │   ├── provider.py       # Google Gemini (gemini-3.5-flash) & OpenAI with fallback
│   │   ├── prompt_manager.py # Anti-AI sanitizer, language matcher, styles & context
│   │   └── reply_generator.py# Context assembly & draft reply generation
│   │
│   └── storage/              # SQLite Persistent Storage
│       └── database.py       # Database for approvals, runtime state & keyword rules
│
├── scripts/                  # Management Utilities
│   ├── authenticate.py       # Interactive phone/code/2FA login script
│   ├── check_connection.py   # Safe non-destructive MTProto connection tester
│   └── generate_session.py   # Telethon StringSession exporter
│
├── setup.sh                  # Universal system-detecting setup script (Linux, macOS, Server)
├── setup.ps1                 # Native Windows PowerShell setup script
├── run.py                    # Universal cross-platform Python CLI launcher
├── start.sh                  # Launches the client daemon
├── authenticate.sh           # Interactive terminal authentication helper
├── test.sh                   # Automated pytest unit test suite runner
├── Dockerfile                # Hardened non-root container image
├── compose.yaml              # Docker Compose deployment with persistent volume
├── entrypoint.sh             # Container startup script with permission checks
├── healthcheck.sh            # Container healthcheck runner
├── system_prompt.txt         # Live editable AI persona instructions
├── requirements.txt          # Python runtime dependencies
├── pyproject.toml            # Project packaging metadata
├── .env.example              # Unified environment configuration template
├── LICENSE                   # Proprietary Source-Available License
└── README.md
```

### Technology Stack:
- **Language**: Python 3.10+ (Asynchronous `asyncio`)
- **Protocol**: MTProto 2.0 via Telethon
- **AI Provider**: Google Gemini 3.5 Flash (via REST gateway with local rule fallback)
- **Database**: SQLite 3 (Built-in, zero external database daemon required)
- **Containerization**: Docker & Docker Compose (`python:3.12-slim` non-root `appuser`)
- **Test Framework**: `pytest` with mocked services (zero live network traffic during tests)

---

## 6. Multi-System Installation & Setup

### 6.1 Arch Linux & Manjaro (Native Local Setup)
```bash
# 1. Clone repository
git clone https://github.com/mkr-infinity/TeleAutomator.git
cd TeleAutomator

# 2. Run universal setup script (auto-detects Arch Linux)
./setup.sh
```

### 6.2 Debian, Ubuntu & Linux Mint
```bash
./setup.sh
```
*(If Python virtual environments are missing on Debian/Ubuntu, `setup.sh` will notify you to run `sudo apt install -y python3-venv python3-pip`).*

### 6.3 Windows (PowerShell & Universal Runner)
**Using PowerShell:**
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\setup.ps1
```
**Using the Universal Cross-Platform Python CLI:**
```bash
python run.py --setup
```

### 6.4 macOS
```bash
./setup.sh
```

### 6.5 24/7 Cloud VPS & Docker Server Deployment
To run continuously on a remote Linux server (Ubuntu, Debian, Arch, CentOS) without keeping your laptop open:
1. SSH into your VPS:
   ```bash
   ssh user@your-server-ip
   ```
2. Clone and run setup:
   ```bash
   git clone https://github.com/mkr-infinity/TeleAutomator.git
   cd TeleAutomator
   ./setup.sh
   ```
3. Authenticate directly inside the SSH terminal:
   ```bash
   ./authenticate.sh
   ```
4. Start via Docker Compose:
   ```bash
   docker compose up -d --build
   ```
5. Check status:
   ```bash
   docker compose ps
   docker compose logs -f
   ```

---

## 7. Step-by-Step Beginner Credentials Setup

### Step 7.1: Telegram API Credentials (my.telegram.org)
1. Open your web browser and navigate to: **[https://my.telegram.org](https://my.telegram.org)**.
2. Enter your phone number with your country code (e.g. `+919876543210` or `+1234567890`).
3. Enter the confirmation code sent to your Telegram app.
4. Click **API development tools**.
5. Fill in the short form:
   - **App title**: `TeleAutomator`
   - **Short name**: `teleautomator`
   - **Platform**: Desktop / Other
6. Click **Create application**.
7. Copy your numeric **`api_id`** and 32-character hexadecimal **`api_hash`**.

---

### Step 7.2: Free Google Gemini API Key
1. Visit **[Google AI Studio](https://aistudio.google.com/app/apikey)**.
2. Sign in with your Google Account.
3. Click **Create API key**.
4. Copy the API key and paste it into `.env`:
   ```env
   AI_ENABLED=true
   AI_PROVIDER=gemini
   AI_API_KEY=AIzaSy...
   AI_MODEL=gemini-3.5-flash
   ```

---

### Step 7.3: First-Time Phone & 2FA Authentication
Run the interactive login utility:
```bash
./authenticate.sh
```
*(Or on Windows / cross-platform: `python run.py --auth`).*
1. Enter your phone number with country code.
2. Enter the 5-digit verification code sent to your Telegram app.
3. If Two-Step Verification (2FA) is enabled, enter your password.
4. The utility saves the session with restrictive permissions (`0600`) and displays your account details.

---

### Step 7.4: Finding & Authorizing Chat IDs
- **Automatic Detection in Logs**: When anyone messages you while the client is active, the terminal prints:
  ```text
  [CHAT DETECTED] Received message from Chat ID: 123456789.
  To allow replies, add to ALLOWED_PRIVATE_CHATS in .env or send /allowchat 123456789 in Saved Messages.
  ```
- **Allow From Your Phone**: Send `/allowchat 123456789` in your **Saved Messages**.
- **For Groups**: Group IDs are negative numbers (e.g. `-1001234567890`).

---

## 8. Automation Modes & Control

TeleAutomator supports three distinct operating modes:

### 8.1 Draft-Only Mode (CLI & Telegram Controlled)
- **What it does**: Incoming messages generate AI draft responses and log them to terminal logs and the SQLite database. **Nothing is ever sent to the chat**.
- **How to activate from CLI**:
  ```bash
  ./start.sh --draft
  # Or:
  python run.py --draft
  # Or:
  python3 -m app.main --mode draft
  ```
- **How to activate from Telegram**: Send `/mode draft` in Saved Messages.

### 8.2 Approval-Required Mode
- **What it does**: When an incoming message arrives, the AI generates a suggested reply and sends a notification to your private **Saved Messages** chat.
- **How to send**: Send `/approve <id>` to dispatch the reply, or `/reject <id>` to discard it.
- **How to activate**: Send `/mode approval` in Saved Messages or pass `--mode approval` via CLI.

### 8.3 Restricted Automation Mode
- **What it does**: Automatically replies to allowlisted chats without requiring manual approval, strictly enforcing per-chat cooldowns and rate limits.
- **How to activate**: Send `/mode auto` in Saved Messages or set `REPLY_MODE=restricted_auto` in `.env`.

---

## 9. Configurable Response Styles

Switch between response styles at any time via Saved Messages or CLI:

| Style | Tone & Description | Activation Command |
| :--- | :--- | :--- |
| **`casual`** *(Default)* | Relaxed, authentic friend texting from a phone. Short, natural sentences. | `/style casual` |
| **`concise`** | Minimal, brief, straight to the point (typically 2-7 words). | `/style concise` |
| **`formal`** | Polite, structured, professional, and respectful. | `/style formal` |
| **`humorous`** | Playful, light-hearted banter with casual wit. | `/style humorous` |

---

## 10. AI System Prompt Customization, Typing Delay & Tone Matching

TeleAutomator is designed to sound indistinguishable from you texting on your phone.

### 10.1 Where & How to Modify the System Prompt

You can customize the AI persona, rules, and reply instructions through two simple methods:

#### Method A: Direct File Edit (`system_prompt.txt`) — Project Root
The core AI persona is stored in plain text right in the project root:
```text
teleautomator/
└── system_prompt.txt     <--- Edit this file directly
```
- Open and edit `system_prompt.txt` using any text editor:
  ```bash
  nano system_prompt.txt
  ```
- **Hot-Reloaded Dynamically**: TeleAutomator automatically re-reads `system_prompt.txt` on every message event. You **do not** need to restart the application or Docker container for changes to take effect!
- If the file is ever deleted or blank, TeleAutomator safely falls back to built-in default instructions.

#### Method B: Live Remote Modification from Saved Messages (`/prompt` & `/setprompt`)
You don't need SSH, terminal access, or code editors to change instructions while on the move:
- **View active prompt**: Send `/prompt` to your Telegram **Saved Messages**.
- **Update prompt on the fly**: Send `/setprompt <your new rules>`:
  ```text
  /setprompt You are texting as Kaif. Be super chill, use short 1-line replies, and mirror Hindi or Hinglish slang.
  ```
- **Reset to default**: Send `/setprompt reset` to clear overrides and restore from `system_prompt.txt`.

---

### 10.2 Adaptive Randomized Human Delay (5 to 60 Seconds)

Real humans do not respond instantaneously within milliseconds, nor do they type at a constant fixed interval. TeleAutomator applies a randomized, adaptive delay ranging between **5 and 60 seconds** that dynamically adjusts to the chat environment:

1. **Environment & Chat Type Adaptation**:
   - **Group Chats (`chat_id < 0`)**: Public group chats are fast-paced. Stalling for a minute makes replies feel outdated. TeleAutomator dynamically tightens the delay bracket to **5 to 25 seconds** so you keep up with the conversation flow.
   - **Private 1-on-1 Direct Messages (`chat_id > 0`)**: Personal chats are more relaxed. Delays naturally spread across **10 to 60 seconds**, mimicking someone seeing a notification, glancing at it, and typing a response.

2. **Content Length & Complexity Scaling**:
   - **Short Replies (< 25 chars)**: Casual greetings (*"yo"*, *"haan bhai"*, *"sure"*) skew faster within the bracket.
   - **Longer Explanations (> 100 chars)**: Multi-sentence answers naturally take longer to formulate and type.

3. **Two-Phase Human Simulation (Reading Pause + Typing Action)**:
   - Rather than broadcasting the `...typing` indicator for 40 seconds straight (which looks fake), TeleAutomator splits the wait:
     - **Phase 1 (Thinking / Reading)**: Silent pause while the user "reads" the message.
     - **Phase 2 (Active Typing)**: Activates Telegram's native `...typing` indicator for the final 2 to 6 seconds before sending.

4. **Emergency Stop Protection**:
   - If an emergency `/stop` command is received in Saved Messages while a message is in its reading delay, the reply is immediately canceled.

5. **Configuration in `.env`**:
   ```env
   # Minimum and maximum randomized delay in seconds (default: 5 to 60)
   MIN_REPLY_DELAY_SECONDS=5
   MAX_REPLY_DELAY_SECONDS=60
   TYPING_DELAY_SECONDS=2
   ```

---

### 10.3 Exact Tone, Slang & Language Matching (Hindi, Hinglish, English)

TeleAutomator dynamically analyzes each incoming message and mirrors the sender:

1. **Exact Language & Dialect Mirroring**:
   - **Hinglish (Latin Script)**:
     - *Incoming:* `"bhai kidhar hai, aaj milna hai kya?"`
     - *Reply:* `"kuch nahi bhai bas ghar pe hu, bata kab aana hai"`
   - **Pure Hindi (Devanagari Script)**:
     - *Incoming:* `"नमस्ते, आप कैसे हैं?"`
     - *Reply:* `"नमस्ते! सब बढ़िया है, आप बताइए?"`
   - **Casual English**:
     - *Incoming:* `"yo did you check that commit?"`
     - *Reply:* `"yeah just saw it, looks good"`
   - **Code-Switching**: If a friend mixes Hindi and English words, TeleAutomator mirrors the exact same mix naturally.

2. **Energy & Brevity Matching**:
   - If the user sends a brief 2-word greeting (`"sup bro"`), the reply stays equally brief and casual (`"chilling, what's up"`).
   - Never outputs corporate fluff, polite bot greetings (*"Certainly! I would be glad to help..."*), or bulleted lists.

3. **Human Alibi Persona (Anti-AI Denial)**:
   - If someone asks: *"Are you an AI?"*, *"Is this ChatGPT?"*, or *"Which model are you?"*, TeleAutomator strictly denies it and laughs it off naturally:
     - English: *"lol what? no, it's me haha typing from my phone"*
     - Hinglish: *"bhai mai hi hu, kya bol raha hai haha 😂"*

---

## 11. Saved Messages Remote Control Center (Commands Reference)

You can manage TeleAutomator entirely from your phone by sending commands to your **Saved Messages** chat (your chat with yourself):

| Command | Action | Example |
| :--- | :--- | :--- |
| **`/status`** | Displays active status, health, mode, style, and pause timer | `/status` |
| **`/mode <draft\|approval\|auto>`**| Switches automation mode dynamically | `/mode draft` |
| **`/style <casual\|concise\|formal\|humorous>`**| Changes AI response style on the fly | `/style concise` |
| **`/chats`** | Lists all allowlisted private contacts and groups | `/chats` |
| **`/allowchat <id>`** | Adds a chat ID to the allowlist immediately | `/allowchat 123456789` |
| **`/removechat <id>`**| Removes a chat from the allowlist | `/removechat 123456789` |
| **`/blockchat <id>`** | Blocks a chat from receiving automated replies | `/blockchat 987654321` |
| **`/pause <duration>`**| Snoozes replies for a duration | `/pause 2h` or `/pause 45m` |
| **`/resume`** | Resumes replies from pause or stop | `/resume` |
| **`/stop`** | **Emergency kill switch**: immediately halts all outgoing messages | `/stop` |
| **`/name <name>`** | Sets your display name for AI prompt assembly | `/name Kaif` |
| **`/prompt`** | Displays active AI system instructions | `/prompt` |
| **`/setprompt <text>`**| Updates AI prompt instructions directly from Telegram | `/setprompt Be chill and brief.` |
| **`/pending`** | Lists drafts awaiting approval (in approval mode) | `/pending` |
| **`/approve <id>`** | Approves and sends draft `#<id>` | `/approve 1` |
| **`/reject <id>`** | Discards draft `#<id>` | `/reject 1` |
| **`/mentiononly on\|off`**| Toggles group mention-only safety | `/mentiononly on` |
| **`/rules`** | Lists active keyword trigger rules | `/rules` |
| **`/addrule <word> => <reply>`**| Adds custom auto-reply rule | `/addrule pricing => Details soon` |
| **`/delrule <word>`** | Deletes a custom keyword rule | `/delrule pricing` |
| **`/help`** | Shows the complete interactive command guide | `/help` |

---

## 12. Custom Keyword Triggers

Create instant, non-AI rule-based auto-replies directly from Telegram:

### Adding a Trigger
Send to **Saved Messages**:
```text
/addrule pricing => Our packages are being updated, will share details shortly!
```

### Viewing All Active Triggers
Send:
```text
/rules
```

### Deleting a Trigger
Send:
```text
/delrule pricing
```

---

## 13. Group Chat Automation & Mention Safety

To prevent noisy groups from being spammed:
- **`/mentiononly on` (Default)**: In groups, TeleAutomator **only** replies when someone explicitly tags your `@username` or replies directly to one of your messages.
- **`/mentiononly off`**: Allows replying to every message in allowlisted groups (recommended only for small private collaboration groups).

---

## 14. Security, Privacy & Anti-Scam Protection

- **Zero Outgoing Links**: AI replies are passed through regex sanitizers that remove all URLs before transmission.
- **Zero Group/Peer Error Leaking**: If an AI request fails, times out, or encounters a rate limit, no error messages, technical details, or canned fallbacks are ever sent to groups or peer contacts. All alerts are sent exclusively to your private **Saved Messages** control channel.
- **Scam Link Detection**: Inbound messages containing crypto traps or invite links (`t.me/+...`) are discarded immediately.
- **Sensitive Content Scrubbing**: Messages containing keywords like `otp`, `password`, `passcode`, `cvv`, or `seed phrase` are ignored.
- **Strict Rate Limiting**: Global cooldown (default: 30s) and per-chat cooldown (default: 60s) protect against Telegram FloodWait errors.
- **Telegram API Terms Compliance**: The application operates within Telegram MTProto client rules and fair-use boundaries without mass unsolicited messaging.
- **Secret Redaction**: Hash keys, tokens, phone numbers, and session strings are automatically redacted in log outputs.

---

## 15. Testing & Verification

Run the automated test suite locally:
```bash
./test.sh
```
Or via the universal launcher:
```bash
python run.py --test
```
All 28 automated unit tests run against mocked Telegram and AI services without sending real messages:
- `test_config.py`: Environment bounds and secret masking
- `test_logger.py`: Phone and token redaction in logs
- `test_message_filter.py`: Broadcast drop, bot command filter, and scam link drop
- `test_privacy_manager.py`: Explicit allowlists and dynamic chat management
- `test_reply_manager.py`: Draft mode, approval dispatch, mode switching, and keyword triggers
- `test_safety_manager.py`: Cooldowns, dedup, and emergency stop
- `test_session_manager.py`: File permissions (0600) and StringSession integrity
- `test_ai_prompt.py`: Response styles, conversation context, and anti-robotic filters

---

## 16. Troubleshooting & FAQ

### Q1: Why does it say "Chat not allowlisted"?
By default, TeleAutomator does not message anyone until they are added to the allowlist. Send `/allowchat <id>` in your Saved Messages or add the ID to `ALLOWED_PRIVATE_CHATS` in `.env`.

### Q2: How do I run strictly in draft mode?
Run `./start.sh --draft` or send `/mode draft` in your Saved Messages.

### Q3: How do I change how the AI speaks?
Send `/style concise`, `/style casual`, `/style formal`, or `/style humorous` in Saved Messages.

### Q4: Where is the system prompt and how do I modify it?
The base system prompt is in `system_prompt.txt` in the root folder. You can edit it directly with `nano system_prompt.txt` (changes take effect immediately without restart), or modify it remotely anytime by sending `/setprompt <new prompt>` in your **Saved Messages**.

### Q5: How does the adaptive delay work?
TeleAutomator emulates realistic human behavior by choosing a randomized delay between 5 and 60 seconds. It automatically adapts to the environment: group chats get tighter delays (5-25s) to keep up with active banter, while private 1-on-1 chats use a more relaxed spread (10-60s). It splits the time into an unread reading pause followed by an active `...typing` indicator for the final 2-6 seconds. You can customize the range in `.env` using `MIN_REPLY_DELAY_SECONDS=5` and `MAX_REPLY_DELAY_SECONDS=60`.

### Q6: Can I run this on my laptop and VPS at the same time?
**No**. Do not run the same session simultaneously from two different locations, as Telegram may terminate the active session.

---

## 17. Roadmap

- [x] MTProto Telegram Client with personal account identity
- [x] Google Gemini AI integration with casual tone and Hindi/English matching
- [x] Human alibi persona (anti-AI disclosure)
- [x] Adaptive randomized human delay (5-60s) adapting to groups and DMs
- [x] Native Telegram typing status simulation
- [x] Dynamic system prompt file and remote chat editing
- [x] Anti-scam and phishing link filter
- [x] Zero outgoing link sanitizer
- [x] Saved Messages remote control center
- [x] Strict Saved Messages error isolation (zero group/peer error leaks)
- [x] Custom keyword auto-reply rules
- [x] Configurable response styles (`casual`, `concise`, `formal`, `humorous`)
- [x] Conversation context and history awareness
- [x] Universal system detection (`setup.sh`, `setup.ps1`, `run.py`)
- [x] Hardened Docker VPS deployment
- [ ] Voice message transcription and voice note auto-replies *(Planned)*
- [ ] Multi-account rotation support *(Planned)*
- [ ] Web dashboard GUI for analytics *(Planned)*

---

## 18. Contribution Guidelines

Contributions are welcome from authorized contributors:
1. Fork the repository.
2. Create a feature branch: `git checkout -b feature/your-feature`.
3. Ensure all tests pass: `./test.sh`.
4. Commit your changes: `git commit -m 'feat: add feature'`.
5. Open a Pull Request on GitHub.

---

## 19. License & Attribution

```text
Repository: https://github.com/mkr-infinity/TeleAutomator
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
