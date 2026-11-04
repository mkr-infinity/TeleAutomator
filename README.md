# Personal Telegram MTProto Client

A secure, production-grade **Personal Telegram MTProto Client** built with Python and Telethon. Designed to operate your personal Telegram identity with strict privacy controls, explicit chat allowlists, automated safety guards, and dual deployment environments: **Local (Arch Linux laptop)** and **Cloud (24/7 Linux VPS via Docker)**.

---

## 📑 Table of Contents
1. [Overview](#1-overview)
2. [Bot Accounts vs. Personal User Clients](#2-bot-accounts-vs-personal-user-clients)
3. [Architecture & Folder Structure](#3-architecture--folder-structure)
4. [Reply Modes & Approval Flow](#4-reply-modes--approval-flow)
5. [Telegram Saved Messages Control Channel](#5-telegram-saved-messages-control-channel)
6. [AI Engine & Data Privacy](#6-ai-engine--data-privacy)
7. [Safety & Anti-Spam Guards](#7-safety--anti-spam-guards)
8. [Local Deployment Quick Start](#8-local-deployment-quick-start)
9. [Cloud VPS Deployment Quick Start](#9-cloud-vps-deployment-quick-start)
10. [Session Security & Revocation](#10-session-security--revocation)
11. [Troubleshooting & Emergency Stop](#11-troubleshooting--emergency-stop)
12. [Telegram API Terms & Compliance](#12-telegram-api-terms--compliance)

---

## 1. Overview

Unlike generic bot scripts, this application runs directly as your **personal Telegram account** over official MTProto protocols. It enables:
- Context-aware reply suggestions for private chats and groups you belong to.
- Three configurable operational modes: **Draft Only**, **Approval Required**, and **Restricted Automation**.
- Remote control and reply approval directly through Telegram **Saved Messages**.
- Offline, privacy-preserving draft mode by default (zero message contents leaked to external AI servers).
- Secret redaction preventing API keys, phone numbers, codes, and tokens from ever entering logs.

---

## 2. Bot Accounts vs. Personal User Clients

| Feature | Telegram Bot API (`BotFather`) | Personal MTProto Client (This Project) |
| :--- | :--- | :--- |
| **Identity** | Bot account with `@...bot` username | **Your actual personal Telegram account** |
| **Authentication** | Static bot token (`123456:ABC-DEF...`) | **MTProto Session** via API ID + API Hash + Phone Code/2FA |
| **Chat Visibility** | Only chats where bot is explicitly added | **Any private chat or group your account participates in** |
| **Message Styling** | Labeled as "bot" by Telegram UI | **Appears as normal messages typed by you** |
| **Privacy Terms** | Bot API Terms | **Telegram API Terms of Service & Fair Use** |

---

## 3. Architecture & Folder Structure

Both local and cloud setups share the exact same underlying logic inside `app/`:

```text
telegram-chat-automation/
├── app/                      # Shared Core Logic
│   ├── __init__.py
│   ├── main.py               # Main runtime entrypoint & signal handling
│   ├── config.py             # Typed configuration loader & validator
│   ├── telegram_client.py    # Telethon MTProto connection & lifecycle
│   ├── session_manager.py    # Local file session & StringSession handler
│   ├── event_handlers.py     # Event registration for messages & commands
│   ├── message_filter.py     # Discard self-messages, service, & non-allowlisted chats
│   ├── reply_manager.py      # Draft, Approval, and Auto orchestrator
│   ├── safety_manager.py     # Cooldowns, dedup, OTP guard, emergency stop
│   ├── privacy_manager.py    # Chat allowlisting, user exclusions, data minimization
│   ├── logger.py             # Structured logging with secret redaction
│   ├── health.py             # Heartbeat monitor & container health check
│   │
│   ├── ai/                   # Modular AI Subsystem
│   │   ├── __init__.py
│   │   ├── provider.py       # LocalRuleProvider, GeminiProvider, OpenAIProvider
│   │   ├── prompt_manager.py # Human-sounding tone & boundary enforcement
│   │   └── reply_generator.py# Orchestrates draft reply creation
│   │
│   └── storage/              # Persistent State
│       ├── __init__.py
│       └── database.py       # SQLite database for dedup & approval queue
│
├── local/                    # Local Laptop Deployment Environment
│   ├── setup.sh              # Python venv creation & dependency install
│   ├── install.sh            # Reinstall requirements
│   ├── authenticate.sh       # Interactive terminal login & StringSession exporter
│   ├── start.sh              # Start local client
│   ├── test.sh               # Run test suite
│   ├── .env.example          # Local environment template
│   └── README.md             # Local setup documentation
│
├── cloud/                    # 24/7 Cloud VPS Deployment Environment
│   ├── Dockerfile            # Secure non-root container image (Python slim)
│   ├── compose.yaml          # Docker Compose orchestration & health check
│   ├── .dockerignore         # Docker context filtering
│   ├── .env.example          # Cloud environment template (StringSession)
│   ├── entrypoint.sh         # Non-root permission checks & startup
│   ├── healthcheck.sh        # Container healthcheck runner
│   ├── deploy.sh             # Cloud build and launch helper
│   └── README.md             # Cloud deployment documentation
│
├── scripts/                  # Utilities
│   ├── authenticate.py       # Interactive Telegram authentication script
│   ├── generate_session.py   # Export cloud string session from local session
│   └── check_connection.py   # Safe non-destructive account verification
│
├── tests/                    # Comprehensive Test Suite (pytest)
├── requirements.txt
├── pyproject.toml
├── .gitignore
├── .dockerignore
└── README.md
```

---

## 4. Reply Modes & Approval Flow

Configured via `REPLY_MODE` in `.env`:

### Mode 1: `draft` (Default)
Generates a draft reply and logs it locally. **Does not send any message.**

### Mode 2: `approval`
Generates a draft and sends a private review prompt to your **Telegram Saved Messages**. Only dispatches the message to the recipient after you explicitly send `/approve <id>`.

### Mode 3: `restricted_auto`
Allows automated sending for allowlisted chats without manual approval, **only when explicitly authorized** via `/auto on` in Saved Messages and all safety cooldowns pass.

---

## 5. Telegram Saved Messages Control Channel

When the client is running, you can manage it in real time by texting commands to your **Saved Messages** (chat with yourself):

| Command | Action |
| :--- | :--- |
| `/approve <id>` | Approves and immediately dispatches pending draft `#<id>` |
| `/reject <id>` | Discards pending draft `#<id>` |
| `/pending` | Lists all drafts currently waiting for your review |
| `/status` | Shows client mode, uptime, error count, and safety status |
| `/auto on` | Authorizes Mode 3 (Restricted Automation) to act without manual approval |
| `/auto off` | Revokes Mode 3 authorization |
| `/stop` | **Emergency kill switch**: immediately halts all outgoing messages |
| `/resume` | Deactivates emergency stop and resumes normal operation |
| `/help` | Shows available commands |

---

## 6. AI Engine & Data Privacy

- **Offline Drafts by Default**: When `AI_ENABLED=false` or `AI_PROVIDER=local`, the application uses `LocalRuleProvider`, generating draft replies without making any external network requests.
- **Pluggable AI Backends**: Supports **Google Gemini** (`AI_PROVIDER=gemini`) and **OpenAI** (`AI_PROVIDER=openai`) using standard library HTTP requests (no bloated SDK dependencies).
- **Communication Guidelines**: Prompts enforce a natural, concise, human-sounding tone. The AI is strictly instructed **never to make commitments, financial promises, or invent facts**.

---

## 7. Safety & Anti-Spam Guards

The `SafetyManager` protects your personal account against Telegram rate limits and accidental loops:
- **Strict Allowlist**: Only chats explicitly listed in `ALLOWED_PRIVATE_CHATS` or `ALLOWED_GROUPS` are processed.
- **Cooldowns**:
  - `GLOBAL_COOLDOWN_SECONDS` (default: 30s) between any two outgoing replies.
  - `PER_CHAT_COOLDOWN_SECONDS` (default: 60s) between replies in the same conversation.
- **Sensitive Content Guard**: Automatically suppresses replies to messages mentioning OTPs, verification codes, 2FA passwords, or bank/crypto credentials.
- **Self-Message & Loop Protection**: Completely ignores messages sent by your own user ID.
- **Consecutive Error Breaker**: Pauses sending for 5 minutes if 5 consecutive errors occur.

---

## 8. Local Deployment Quick Start

On your Arch Linux laptop:
```bash
# 1. Setup virtual environment & dependencies
./local/setup.sh

# 2. Edit .env with your credentials from https://my.telegram.org/apps
nano .env

# 3. Authenticate your personal Telegram account
./local/authenticate.sh

# 4. Start the client
./local/start.sh
```
See [`local/README.md`](local/README.md) for full instructions.

---

## 9. Cloud VPS Deployment Quick Start

On your Linux server with Docker installed:
```bash
# 1. Generate cloud session string on your laptop
python3 scripts/generate_session.py

# 2. Copy project to your server
rsync -avz --exclude='.venv' --exclude='data' ./ user@server-ip:~/telegram-chat-automation/

# 3. SSH into server, configure cloud/.env with TG_SESSION_STRING
cd cloud
cp .env.example .env
nano .env

# 4. Launch in background
./deploy.sh
```
See [`cloud/README.md`](cloud/README.md) for full instructions.

---

## 10. Session Security & Revocation

- **Local Permissions**: Session files in `data/` are created with `0600` permissions (readable only by the owner).
- **Cloud Secrets**: `TG_SESSION_STRING` gives access to your Telegram account. Never commit it to git or paste it in public chat logs.
- **Single Instance**: Do not run local and cloud clients simultaneously with the same session.
- **Session Revocation**: If you ever suspect a session string was exposed, open Telegram on your phone:
  **Settings → Devices → Terminate Session**.

---

## 11. Troubleshooting & Emergency Stop

### How to stop the client immediately
- **Locally**: Press `Ctrl+C` in your terminal.
- **In Cloud**: Run `docker compose down` inside `cloud/`.
- **From your Phone**: Send `/stop` in **Saved Messages** to activate the emergency kill switch.

### Running Tests
To verify all 20 automated unit tests:
```bash
./local/test.sh
```

---

## 12. Telegram API Terms & Compliance

- This application complies with Telegram MTProto API rules by acting as a user-client tool.
- Automation is strictly opt-in and restricted to allowlisted chats. Mass marketing, unsolicited advertising, or spamming is strictly prohibited under Telegram terms.
- No personal user messages are retained permanently or uploaded to external servers without explicit configuration.
