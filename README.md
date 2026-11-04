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

> 🚀 **Deploying to a Cloud VPS, Docker, or Render.com?**  
> Check out the complete step-by-step beginner guide with Render Blueprint support: **[DEPLOYMENT.md](DEPLOYMENT.md)**.

---

## ⚡ Quickstart in 60 Seconds

```bash
# 1. Clone repository
git clone https://github.com/mkr-infinity/TeleAutomator.git && cd TeleAutomator

# 2. Run universal setup (auto-detects Arch, Ubuntu, Debian, macOS, Windows)
./setup.sh

# 3. Authenticate with your Telegram account (Phone, OTP, 2FA)
./authenticate.sh

# 4. Start TeleAutomator
./start.sh
```
*(Windows users: Run `python run.py --setup` -> `python run.py --auth` -> `python run.py`)*

---

## 📑 Table of Contents
1. [Overview](#1-overview)
2. [Bot vs. MTProto Client](#2-bot-vs-mtproto-client)
3. [Key Features](#3-key-features)
4. [Message Lifecycle](#4-message-lifecycle)
5. [Operating Modes](#5-operating-modes)
6. [Saved Messages Remote Control](#6-saved-messages-remote-control)
7. [System Prompt & Persona Tuning](#7-system-prompt--persona-tuning)
8. [Adaptive Human Delay & Tone Matching](#8-adaptive-human-delay--tone-matching)
9. [Security & Anti-Leak Safety](#9-security--anti-leak-safety)
10. [Testing & Verification](#10-testing--verification)
11. [Troubleshooting](#11-troubleshooting)
12. [License & Attribution](#12-license--attribution)

---

## 1. Overview

**TeleAutomator** automates your **real personal Telegram account** using Python and MTProto 2.0. It listens to incoming messages, evaluates privacy rules, detects tone and language, and drafts or sends context-aware replies using **Google Gemini AI**.

---

## 2. Bot vs. MTProto Client

| Feature | Telegram Bot (`@BotFather`) | TeleAutomator Personal MTProto Client |
| :--- | :--- | :--- |
| **Account Identity** | Bot badge (`@example_bot`) | **Your real personal Telegram account** |
| **Authentication** | Bot Token (`123456:ABC...`) | **MTProto Session** via Phone Login |
| **Chat Reach** | Only where explicitly added | **Any chat or group you participate in** |
| **Message Appearance**| Tagged as a bot | **Indistinguishable from you typing on phone** |
| **Bot-to-Bot Chats** | Prohibited by Telegram | **Fully supported** |

---

## 3. Key Features

- **Context-Aware AI Generation**: Understands conversation flow, reply chains, and chat history.
- **Tone & Language Mirroring**: Automatically matches Hindi (Devanagari), Hinglish, or casual English slang.
- **Human Alibi Persona**: Strictly denies being an AI; casually laughs off bot inquiries.
- **Adaptive Delay (5 to 60s)**: Fast group banter (5-25s) vs. relaxed 1-on-1 chats (10-60s) with active typing indicator simulation.
- **Zero Group/Peer Error Leaks**: All errors, rate limits, and fallbacks route strictly to **Saved Messages**.
- **Remote Telegram Control**: Manage modes, prompts, styles, and allowlists directly from **Saved Messages**.
- **Scam & Link Defense**: Discards crypto bait and phishing invite links; strips outgoing URLs.

---

## 4. Message Lifecycle

```text
[ Inbound Message ] ──► [ Scam & OTP Filters ] ──► [ Match Keyword Rules? ]
                                                            │
                                                     (No Keyword Match)
                                                            │
                                                            ▼
                                                [ Context & History Assembly ]
                                                            │
                                                            ▼
                                                [ Google Gemini Generation ]
                                                            │
                                                            ▼
                             ┌──────────────────────────────┴─────────────────────────────┐
                             ▼                                                            ▼
                    [ Mode: Draft ]                                             [ Mode: Auto ]
                    Logs to DB & terminal;                                      Applies 5-60s adaptive delay
                    never sends to chat.                                        and sends via MTProto.
```

---

## 5. Operating Modes

Switch modes at any time from terminal or Saved Messages:

| Mode | Description | How to Activate |
| :--- | :--- | :--- |
| **`draft`** *(Default)* | Generates and logs drafts to database; **never sends to chat**. | `/mode draft` or `./start.sh --draft` |
| **`approval`** | Sends drafts to your **Saved Messages** for `/approve <id>` dispatch. | `/mode approval` or `./start.sh --mode approval` |
| **`restricted_auto`**| Automatically replies to allowlisted chats with adaptive delays. | `/mode auto` or set `REPLY_MODE=restricted_auto` in `.env` |

---

## 6. Saved Messages Remote Control

Manage TeleAutomator straight from your phone by texting your **Saved Messages** (chat with yourself):

| Command | Action | Example |
| :--- | :--- | :--- |
| **`/status`** | Displays active mode, style, and safety pause status | `/status` |
| **`/mode <draft\|approval\|auto>`** | Switches operating mode dynamically | `/mode auto` |
| **`/style <casual\|concise\|formal\|humorous>`** | Changes AI speaking style on the fly | `/style concise` |
| **`/chats`** | Lists allowlisted private contacts and groups | `/chats` |
| **`/allowchat <id>`** | Adds a chat ID to allowlist | `/allowchat 123456789` |
| **`/removechat <id>`** | Removes a chat from allowlist | `/removechat 123456789` |
| **`/prompt`** | Views active AI prompt instructions | `/prompt` |
| **`/setprompt <text>`** | Updates prompt instructions in real time | `/setprompt Be chill and brief.` |
| **`/addrule <trigger> => <reply>`** | Creates non-AI keyword auto-reply | `/addrule pricing => Details soon!` |
| **`/rules`** | Lists all custom keyword triggers | `/rules` |
| **`/pause <duration>`** | Snoozes auto-replies | `/pause 2h` or `/pause 30m` |
| **`/resume`** | Resumes paused replies | `/resume` |
| **`/stop`** | **Emergency kill switch**: halts all outgoing messages | `/stop` |
| **`/help`** | Shows complete interactive command reference | `/help` |

---

## 7. System Prompt & Persona Tuning

Customize how the AI talks using either method:

### Method 1: Local File (`system_prompt.txt`)
Edit [`system_prompt.txt`](system_prompt.txt) in the project root:
```bash
nano system_prompt.txt
```
*Changes are hot-reloaded dynamically on every incoming message without restarting the server.*

### Method 2: Remote Control via Telegram
Send `/prompt` to inspect, or `/setprompt <new rules>` to modify instructions instantly from your phone. Send `/setprompt reset` to restore defaults.

---

## 8. Adaptive Human Delay & Tone Matching

### Realistic 5-60 Second Delay
To prevent bot-detection patterns, TeleAutomator adapts its delay to the environment:
- **Group Chats**: Dynamic bracket of **5 to 25 seconds** to match fast group banter.
- **Private DMs**: Relaxed bracket of **10 to 60 seconds** mimicking human reading habits.
- **Two-Phase Action**: Pauses silently to "read", then triggers Telegram's native `...typing` indicator for the final 2-6 seconds.
- Configure in `.env`: `MIN_REPLY_DELAY_SECONDS=5` and `MAX_REPLY_DELAY_SECONDS=60`.

### Exact Tone & Language Mirroring
- **Hinglish**: `"kya scene hai bhai?"` ──► `"kuch nahi bhai bas chilling, tu bata"`
- **Hindi (Devanagari)**: `"नमस्ते, कैसे हैं?"` ──► `"नमस्ते! सब बढ़िया है, आप बताइए?"`
- **English**: `"yo did you check the commit?"` ──► `"yeah just reviewed it, looks solid"`
- **Human Alibi**: If asked *"are you a bot?"*, it laughs it off casually (*"lol what? no it's me haha"*).

---

## 9. Security & Anti-Leak Safety

- **Zero Group Error Leaks**: Errors and API timeouts are sent strictly to **Saved Messages**. Zero error notices ever reach recipient chats.
- **Link Stripping**: Regex sanitizers strip all outgoing URLs to prevent inadvertent spam.
- **Scam Protection**: Discards invite traps (`t.me/+...`) and messages requesting OTPs or passwords.
- **Rate Limiting**: Enforces global (30s) and per-chat (60s) cooldowns against FloodWait limits.

---

## 10. Testing & Verification

Run the automated test suite locally:
```bash
./test.sh
# Or via universal runner:
python run.py --test
```
**28 passing unit tests** covering configuration, safety guards, adaptive delay, and mock MTProto workflows without network side-effects.

---

## 11. Troubleshooting

| Issue | Cause & Solution |
| :--- | :--- |
| **"Chat not allowlisted"** | Send `/allowchat <id>` in Saved Messages or add ID to `ALLOWED_PRIVATE_CHATS` in `.env`. |
| **"API Key Invalid"** | Verify your free Gemini key at [Google AI Studio](https://aistudio.google.com/app/apikey) and set in `.env`. |
| **Need 24/7 Hosting?** | Follow the beginner guide in **[DEPLOYMENT.md](DEPLOYMENT.md)**. |

---

## 12. License & Attribution

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

Licensed under the [Proprietary Source-Available License](LICENSE). Free for personal use.
