# TeleAutomator - Telegram Chat Automation v2.0.5

![TeleAutomator Banner](assets/banner.png)

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![MTProto Telethon](https://img.shields.io/badge/protocol-MTProto%20Telethon-informational.svg)](https://github.com/LonamiWebs/Telethon)
[![AI Supported](https://img.shields.io/badge/AI-Gemini%20%7C%20OpenAI%20%7C%20Custom-orange.svg)](DEPLOYMENT.md)
[![License](https://img.shields.io/badge/license-Source--Available-red.svg)](LICENSE)
[![Tests Passing](https://img.shields.io/badge/tests-65%2F65%20passed-brightgreen.svg)](test.sh)

> 🚀 **Deploying to Railway, Render, or Cloud VPS 24/7?**  
> For complete step-by-step cloud deployment walkthroughs, automated build guides, and environment variable configurations, see **[DEPLOYMENT.md](DEPLOYMENT.md)**.

---

## ⚡ Quickstart (Local)

```bash
# 1. Clone repository
git clone https://github.com/mkr-infinity/TeleAutomator.git && cd TeleAutomator

# 2. Universal automated setup
./setup.sh

# 3. Authenticate with your Telegram account (Phone, OTP, 2FA)
./authenticate.sh

# 4. (Optional) Export your headless Cloud session string:
./session.sh

# 5. Start TeleAutomator
./start.sh
```
*(Windows / cross-platform: `python run.py --setup` -> `python run.py --auth` -> `python run.py --session` -> `python run.py`)*

---

## 📑 Operating Modes

Switch modes on the fly from terminal or your Telegram **Saved Messages**:

| Mode | Description | How to Activate |
| :--- | :--- | :--- |
| **`draft`** *(Default)* | Generates and logs drafts to SQLite; **never sends to chat**. | `/mode draft` or `./start.sh --draft` |
| **`approval`** | Sends drafts to your **Saved Messages** for `/approve <id>` dispatch. | `/mode approval` or `./start.sh --mode approval` |
| **`restricted_auto`**| Automatically replies to allowlisted chats with adaptive delays. | `/mode auto` or set `REPLY_MODE=restricted_auto` |

---

## 📱 Saved Messages Remote Control Reference

Manage your automation straight from your phone by texting your **Saved Messages** (chat with yourself):

### Permanent Group Context & Memory
| Command | Action | Example |
| :--- | :--- | :--- |
| **`/syncpins [chat_id]`** | Auto-fetches pinned messages from group(s) as permanent context | `/syncpins -1001234567890` or `/syncpins` |
| **`/setcontext <id> <notes>`** | Saves permanent rules/facts for a group so AI never talks nonsense | `/setcontext -1001234 Tech team, building AI agents.` |
| **`/showcontext <chat_id>`** | Inspects active pinned info and custom permanent notes for a group | `/showcontext -1001234567890` |
| **`/delcontext <chat_id>`** | Removes permanent context for a group | `/delcontext -1001234567890` |
| **`/contextttl <hours>`** | Sets conversation auto-aging window (default: 2.0 hours) | `/contextttl 2.0` |
| **`/clearcontext <chat_id>`** | Resets rolling conversation cache (guaranteed zero Telegram message deletions) | `/clearcontext -1001234567890` |

### Core Controls & Identity
| Command | Action | Example |
| :--- | :--- | :--- |
| **`/status`** | Displays active mode, models, quota, quiet hours, and DataFrame table | `/status` |
| **`/name <name\|sync>`** | Sets display persona name, or syncs automatically from Telegram profile | `/name sync` or `/name Kaif` |
| **`/mode <draft\|approval\|auto>`** | Switches operating mode dynamically | `/mode auto` |
| **`/style <casual\|concise\|formal\|humorous>`** | Changes AI speaking persona on the fly | `/style concise` |
| **`/lang <dynamic\|english\|hindi\|...>`** | Sets target language (dynamic match or forced language) | `/lang dynamic` |
| **`/chats`** | Displays active allowlisted chats in structured DataFrame format | `/chats` |
| **`/allowchat <id>`** | Adds a chat ID to the allowlist directly from phone | `/allowchat 123456789` |
| **`/removechat <id>`** | Removes a chat from allowlist | `/removechat 123456789` |
| **`/mentiononly <on\|off>`** | Reply in groups only when tagged or replied to | `/mentiononly on` |

### AI Models, Quota & Cooldowns
| Command | Action | Example |
| :--- | :--- | :--- |
| **`/aiconfig`** | Inspects provider, base URL, temperature, and reasoning parameters | `/aiconfig` |
| **`/setai`** | Custom AI setup dashboard & 1-line configuration | `/setai <provider> <api_key> [endpoint] [model]` |
| **`/apikey <key>`** | Update active AI API key directly from Telegram without restarts | `/apikey <your_api_key>` |
| **`/baseurl <url>`** | Update custom endpoint URL | `/baseurl https://api.your-provider.com/v1` |
| **`/provider <name>`** | Switch AI engine (`custom`, `gemini`, `openai`, `nvidia`, `local`) | `/provider custom` |
| **`/model <name>`** | Switch AI candidate model (supports comma-separated fallbacks) | `/model <model_name>` |
| **`/usage`** | Displays 24h consumption, total token usage, and remaining free quota | `/usage` |
| **`/quotathreshold <tokens>`** | Sets 24h token warning alert limit (default: 100,000 tokens) | `/quotathreshold 50000` |
| **`/quotaalert <on\|off>`** | Toggles daily quota alert warnings to Saved Messages | `/quotaalert on` |
| **`/reasoning <low\|medium\|high\|off>`** | Adjusts reasoning effort for reasoning-capable models | `/reasoning low` |
| **`/reaction <on\|off>`** | Toggles natural emoji reactions (pool of 26 mobile emojis) | `/reaction on` |
| **`/reactioncooldown <min> <max>`**| Sets randomized reaction interval (default: 3s–9s) | `/reactioncooldown 3 9` |
| **`/chatcooldown <min> <max>`** | Sets randomized per-chat reply cooldown (default: 5s–60s) | `/chatcooldown 5 60` |
| **`/quiethours <on\|off\|start end>`**| Simulates human sleep schedule (pauses replies & reactions) | `/quiethours on 23:00 07:00` |
| **`/stop`** | **Emergency kill switch**: immediately halts all outgoing messages | `/stop` |
| **`/resume`** | Resumes automation and clears all stops/pauses | `/resume` |

---

## 🧪 Testing & Verification

Run the automated test suite locally:
```bash
./test.sh
# Or via universal runner:
python run.py --test
```
**65 passing unit tests** covering configuration, safety guards, quiet hours, randomized cooldowns, permanent context caching, pinned message syncing, adaptive typing, and mock MTProto workflows.

---

## ☕ Support & Donations

If TeleAutomator saves you time or empowers your personal workflow, consider supporting development:

- ☕ **Buy Me a Coffee**: [https://buymeacoffee.com/mkr_infinity](https://buymeacoffee.com/mkr_infinity)
- 🇮🇳 **UPI (India)**: `mkr-infinity@ybl`

---

## 📄 License & Attribution

Licensed under the [Proprietary Source-Available License](LICENSE). Free for personal use.  
Author: **Mohammad Kaif Raja ([@mkr-infinity](https://github.com/mkr-infinity))**
