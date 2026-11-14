# TeleAutomator — Setup Requirements & Environment Guide

This guide explains **every required and recommended setting** needed to run TeleAutomator. Whether you are running locally on your laptop, on a VPS, or deploying 24/7 on cloud platforms (Railway, Render, Docker), follow these steps to get your keys and configure your `.env` file.

---

## 📋 Quick Reference: What Do I Need?

| Category | Variable Name | Required? | Where to Get It |
| :--- | :--- | :---: | :--- |
| **Telegram Core** | `TG_API_ID` | **YES** | [my.telegram.org](https://my.telegram.org) |
| **Telegram Core** | `TG_API_HASH` | **YES** | [my.telegram.org](https://my.telegram.org) |
| **AI Brain** | `AI_API_KEY` | **YES** | [Google AI Studio](https://aistudio.google.com/app/apikey) (Free) or [OpenAI](https://platform.openai.com/api-keys) |
| **Bot & Mini App** | `BOT_API_KEY` | **Recommended** | [@BotFather](https://t.me/BotFather) on Telegram |
| **Bot & Mini App** | `BOT_AUTHORIZED_USERS` | **Recommended** | Your own Telegram ID from [@userinfobot](https://t.me/userinfobot) |
| **Cloud Deploy** | `TG_SESSION_STRING` | Cloud only | Generated once via `./session.sh` |
| **Chat Scope** | `ALLOWED_PRIVATE_CHATS` | Optional | Telegram user IDs you permit the AI to reply to |
| **Chat Scope** | `ALLOWED_GROUPS` | Optional | Telegram group IDs (starts with `-100...`) |

---

## 1. Telegram Client Credentials (Core MTProto)

TeleAutomator connects directly to Telegram's network using the official MTProto protocol. Telegram requires every client app to identify itself with an App ID and Hash.

### `TG_API_ID` & `TG_API_HASH`
* **Why it's needed**: Connects your personal Telegram account to send and receive messages automatically.
* **Where to find it**:
  1. Open your browser and go to **[https://my.telegram.org](https://my.telegram.org)**.
  2. Log in using your Telegram phone number (in international format, e.g. `+1...` or `+91...`).
  3. Telegram will send a confirmation code to your Telegram app. Enter it to sign in.
  4. Click on **API development tools**.
  5. Fill in the short form:
     * **App title**: `TeleAutomator` (or any name you like)
     * **Short name**: `teleautomator`
     * **Platform**: Desktop (or Other)
  6. Click **Create application**.
  7. Copy your **`App api_id`** (a number like `12345678`) and **`App api_hash`** (a 32-character string like `0123456789abcdef0123456789abcdef`).
* **Example in `.env`**:
  ```env
  TG_API_ID=12345678
  TG_API_HASH=0123456789abcdef0123456789abcdef
  ```

> [!IMPORTANT]
> Never share your `TG_API_ID` or `TG_API_HASH` publicly. Keep your `.env` file private and never commit it to Git.

---

## 2. Remote Control Bot & Mini App (Recommended)

To control TeleAutomator from your phone (change models, toggle sleep mode, approve draft replies, and use the Mini App GUI) without cluttering your personal account, configure a dedicated Telegram Control Bot.

### `BOT_API_KEY`
* **Why it's needed**: Powers the Telegram Control Bot and serves the Telegram Mini App dashboard.
* **Where to find it**:
  1. Open Telegram and search for the official **[@BotFather](https://t.me/BotFather)**.
  2. Send `/newbot` to BotFather.
  3. Enter a friendly name for your bot (e.g. `My Assistant Control`).
  4. Enter a unique username ending in `bot` (e.g. `my_assistant_ctrl_bot`).
  5. BotFather will reply with your HTTP API token in the format `1234567890:AAE_xxxxxxxxxxxxxxxxxxxx`.
* **Example in `.env`**:
  ```env
  BOT_API_KEY=1234567890:AAE_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
  ```

### `BOT_AUTHORIZED_USERS`
* **Why it's needed**: Security protection. Ensures **only you** (and people you explicitly authorize) can send commands to your bot and access the Mini App dashboard. Anyone else messaging the bot is blocked with an access note.
* **Where to find it**:
  1. Open Telegram and message **[@userinfobot](https://t.me/userinfobot)** or **[@getmyid_bot](https://t.me/getmyid_bot)**.
  2. It will reply immediately with your numeric Telegram user ID (e.g. `555000111`).
* **Example in `.env`**:
  ```env
  # Your numeric Telegram user ID (or comma-separated if adding a co-manager)
  BOT_AUTHORIZED_USERS=555000111
  ```

---

## 3. AI Reply Engine

TeleAutomator uses an AI model to read messages in context and draft human-like replies.

### `AI_PROVIDER`
* **Why it's needed**: Specifies which AI company or API protocol to use.
* **Options**:
  * `"gemini"` *(Recommended default: fastest and has a generous free tier)*
  * `"openai"` *(Official OpenAI API)*
  * `"custom"` *(Any OpenAI-compatible API: Groq, DeepSeek, Together, Ollama, vLLM, etc.)*
* **Example in `.env`**:
  ```env
  AI_PROVIDER=gemini
  ```

### `AI_API_KEY`
* **Why it's needed**: Authenticates your requests with the AI provider.
* **Where to find it**:
  * **Google Gemini (Free)**: Visit **[https://aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)**, sign in with your Google account, and click **Create API key**.
  * **OpenAI**: Visit **[https://platform.openai.com/api-keys](https://platform.openai.com/api-keys)**, create an account, and generate a new secret key.
  * **Custom Provider**: Copy the API key from your provider's dashboard (e.g. Groq, OpenRouter, DeepSeek).
* **Example in `.env`**:
  ```env
  AI_API_KEY=AIzaSyD-your-gemini-key-here
  ```

### `AI_MODEL`
* **Why it's needed**: Chooses which model generates replies. You can supply multiple models separated by commas for automatic fallback if one model is rate-limited.
* **Examples**:
  * For Gemini: `gemini-2.5-flash-lite,gemini-2.5-flash`
  * For OpenAI: `gpt-4o-mini,gpt-4o`
  * For Custom: `deepseek-chat` or `llama-3.3-70b-versatile`
* **Example in `.env`**:
  ```env
  AI_MODEL=gemini-2.5-flash-lite
  ```

### `AI_BASE_URL` *(Only if using `AI_PROVIDER=custom`)*
* **Why it's needed**: Directs requests to your third-party OpenAI-compatible endpoint. Leave blank for standard Gemini or OpenAI.
* **Example in `.env`**:
  ```env
  AI_BASE_URL=https://api.groq.com/openai/v1
  ```

---

## 4. Chat Allowlist & Privacy Scope

By default, TeleAutomator stays completely quiet until you tell it which chats it is allowed to reply to.

> [!TIP]
> You can leave these completely blank initially! You can allow or remove chats anytime straight from your Telegram phone by typing `/allowchat <id>` in your Control Bot or tapping **Allow** inside the Telegram Mini App.

### How to Find Any Chat ID
1. **Private User Chat ID**:
   * Forward any message from that user to **[@userinfobot](https://t.me/userinfobot)**. It will reply with their user ID (e.g. `987654321`).
2. **Group or Supergroup ID**:
   * Add **[@RawDataBot](https://t.me/RawDataBot)** to the group temporarily. It will output a JSON message showing the `"chat": { "id": -1001987654321 }`.
   * Group IDs are **always negative** and start with `-100`.

### `ALLOWED_PRIVATE_CHATS`
* **Example in `.env`**:
  ```env
  ALLOWED_PRIVATE_CHATS=987654321,123456789
  ```

### `ALLOWED_GROUPS`
* **Example in `.env`**:
  ```env
  ALLOWED_GROUPS=-1001987654321,-1001765432109
  ```

### `REPLY_MODE`
* **Options**:
  * `restricted_auto` *(Default)*: Automatically drafts and sends replies to allowlisted chats using humanized typing delays.
  * `approval`: Drafts replies and sends them to your Control Bot first. You reply `/approve <id>` or swipe in the Mini App to send.
  * `draft`: Generates and logs drafts to local SQLite memory for testing; never sends anything to Telegram.
* **Example in `.env`**:
  ```env
  REPLY_MODE=restricted_auto
  ```

---

## 5. Cloud Platform Credentials (Railway, Render, Docker)

When running locally or on a standard Linux VPS, TeleAutomator saves your login session file automatically to `data/telegram_client.session`.

When deploying on headless cloud platforms (like **Railway** or **Render**), disk storage is ephemeral, so you store the session as a string:

### `TG_SESSION_MODE` & `TG_SESSION_STRING`
* **How to generate it**:
  1. On your computer, run:
     ```bash
     ./session.sh
     # Or cross-platform:
     python run.py --session
     ```
  2. Follow the prompt to log in with your Telegram account.
  3. The script will output a secure string starting with `1B...` (approx. 200–300 characters).
  4. Paste that string into your cloud service's Environment Variables.
* **Example in `.env`**:
  ```env
  TG_SESSION_MODE=string
  TG_SESSION_STRING=1BVtsOH...your_generated_session_string...
  ```

---

## 6. Minimal Ready-to-Copy `.env` Starter Template

Here is a clean template with the essential variables. Save this as `.env` in your project root:

```env
# ==========================================
# 1. Telegram Client Credentials (Required)
# Get from https://my.telegram.org
# ==========================================
TG_API_ID=12345678
TG_API_HASH=0123456789abcdef0123456789abcdef

# Session storage: 'local' for PC/VPS, 'string' for Railway/Render
TG_SESSION_MODE=local
TG_SESSION_STRING=

# ==========================================
# 2. Control Bot & Mini App (Recommended)
# Get token from @BotFather, user ID from @userinfobot
# ==========================================
BOT_API_KEY=1234567890:AAE_your_bot_token_here
BOT_AUTHORIZED_USERS=555000111

# ==========================================
# 3. AI Reply Engine (Required)
# Free key from https://aistudio.google.com/app/apikey
# ==========================================
AI_ENABLED=true
AI_PROVIDER=gemini
AI_API_KEY=AIzaSyYourGeminiApiKeyHere
AI_MODEL=gemini-2.5-flash-lite

# ==========================================
# 4. Automation & Safety Rules
# ==========================================
REPLY_MODE=restricted_auto
QUIET_HOURS_ENABLED=true
QUIET_HOURS_START=02:00
QUIET_HOURS_END=08:00
DEFAULT_CHAT_LANGUAGE=dynamic
```

---

## 7. Next Steps

Once your `.env` file is saved:
1. **Verify your credentials**: Run `./authenticate.sh` (or `python run.py --auth`) to verify your login.
2. **Start the engine**: Run `./start.sh` (or `python run.py`).
3. **Open the Mini App**: Open your Telegram Control Bot on your phone, click **Open** (the persistent menu button in the bottom left), and control your setup visually!
