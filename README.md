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
[![Tests Passing](https://img.shields.io/badge/tests-39%2F39%20passed-brightgreen.svg)](test.sh)

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

# (Optional) View your exported cloud session string in terminal (local mode):
./session.sh

# 4. Start TeleAutomator
./start.sh
```
*(Windows / cross-platform: `python run.py --setup` -> `python run.py --auth` -> `python run.py --session` -> `python run.py`)*

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
| **`/status`** | Displays active mode, style, language, reactions, and cooldown status | `/status` |
| **`/mode <draft\|approval\|auto>`** | Switches operating mode dynamically | `/mode auto` |
| **`/style <casual\|concise\|formal\|humorous>`** | Changes AI speaking style on the fly | `/style concise` |
| **`/lang <dynamic\|english\|hindi\|...>`** | Sets target language (dynamic detection or forced language) | `/lang dynamic` or `/lang english` |
| **`/reaction <on\|off>`** | Toggles natural emoji reactions on messages | `/reaction on` |
| **`/reactioncooldown <count> <mins>`** | Customizes reaction rate limit (default 4 per 10m) | `/reactioncooldown 4 10` |
| **`/chatcooldown <seconds>`** | Sets per-chat reply cooldown timer | `/chatcooldown 30` |
| **`/globalcooldown <seconds>`** | Sets global reply cooldown timer | `/globalcooldown 15` |
| **`/chats`** | Lists allowlisted private contacts and groups | `/chats` |
| **`/allowchat <id>`** | Adds a chat ID to allowlist | `/allowchat 123456789` |
| **`/removechat <id>`** | Removes a chat from allowlist | `/removechat 123456789` |
| **`/mentiononly <on\|off>`** | Reply only when mentioned or replied to in groups | `/mentiononly on` |
| **`/model <name>`** | Switches active AI model (e.g. `gemini-2.5-flash-lite`, `gpt-4o-mini`) | `/model gemini-2.5-flash-lite` |
| **`/baseurl <url>`** | Custom base URL for NVIDIA, Groq, DeepSeek, or Ollama | `/baseurl https://integrate.api.nvidia.com/v1` |
| **`/provider <name>`** | Switches AI provider backend (`gemini`, `openai`, `nvidia`, `custom`, `local`) | `/provider nvidia` |
| **`/chatty <0-100>`** | Sets group banter participation % for non-mention messages | `/chatty 15` |
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

### Recommended Max Word Limit
> [!TIP]
> **Recommended Word Limit:** Keep system prompt between **150 to 300 words** (~200–350 tokens). Small LLMs (like Gemini Flash) maintain the highest instruction adherence and avoid robotic verbosity when prompts stay concise.

### Method 1: Local File (`system_prompt.txt`)
Edit [`system_prompt.txt`](system_prompt.txt) in the project root:
```bash
nano system_prompt.txt
```
*Changes are hot-reloaded dynamically on every incoming message without restarting the server.*

### Method 2: Remote Control via Telegram
Send `/prompt` to inspect, or `/setprompt <new rules>` to modify instructions instantly from your phone.

---

## 8. Adaptive Human Delay & Multi-Message Texting

### Multi-Message Split Replies
Real humans text in short, rapid bursts rather than giant monolithic essays. When TeleAutomator has more than one thought to share, it naturally divides the reply into **2 or 3 separate messages** separated by natural thought boundaries or newlines, with an organic 1.0-1.8s typing delay between them (never cutting off words or breaking meaning mid-sentence).

### Realistic 5-60 Second Delay
To prevent bot-detection patterns, TeleAutomator adapts its delay to the environment:
- **Group Chats**: Dynamic bracket of **5 to 25 seconds** to match fast group banter.
- **Private DMs**: Relaxed bracket of **10 to 60 seconds** mimicking human reading habits.
- **Two-Phase Action**: Pauses silently to "read", then triggers Telegram's native `...typing` indicator for the final 2-6 seconds.
- Configure in `.env`: `MIN_REPLY_DELAY_SECONDS=5` and `MAX_REPLY_DELAY_SECONDS=60`.

### Gen-Z Slang & Tone Matching
- Uses natural casual shortcuts: `"u"`, `"r"`, `"rn"`, `"idk"`, `"ngl"`, `"tbh"`, `"fr"`, `"wbu"`.
- If someone texts `"hii"`, it replies `"hii"` or `"hello"` without unasked paragraphs.
- **Human Alibi**: If asked *"are you a bot?"* or challenged about identity, it replies with friendly disbelief (*"seriously bro u think I am not real? 😂"* or *"bruh u fr rn? it's me lol"*).
- **Anti-Code Scrubbing**: Never writes code blocks, `/etc` file paths, brackets `[]`, or braces `{}`.

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
**39 passing unit tests** covering configuration, safety guards, adaptive delay, multi-message splitting, reactions, language control, custom OpenAI/NVIDIA endpoints, database context caching, and mock MTProto workflows without network side-effects.

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
