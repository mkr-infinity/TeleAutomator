# Local Deployment Guide (Arch Linux & Standard Linux)

This directory contains the scripts and configuration required to run your personal Telegram MTProto client locally on your laptop.

---

## 🚀 Quick Start in 3 Steps

### Step 1: Run Setup
Ensure you are in the `local/` folder (or project root) and execute:
```bash
./local/setup.sh
```
What this does:
- Detects Python 3.10+
- Creates a virtual environment in `.venv/`
- Installs all dependencies (`telethon`, `python-dotenv`, `pytest`)
- Creates a private `.env` file from `.env.example` with restricted `0600` permissions
- Creates a protected `data/` folder with `0700` permissions

---

### Step 2: Configure Your Credentials
Open `.env` in your preferred editor (e.g., `nano .env` or `vim .env`):
```env
TG_API_ID=12345678
TG_API_HASH=0123456789abcdef0123456789abcdef

# Specify which private chat IDs or group IDs the client is permitted to interact with
# (Leaves all other chats ignored for safety)
ALLOWED_PRIVATE_CHATS=123456789
ALLOWED_GROUPS=

# Reply Mode: draft (default), approval, or restricted_auto
REPLY_MODE=draft
```

---

### Step 3: Authenticate Interactively
Run the authentication script:
```bash
./local/authenticate.sh
```
What happens during authentication:
1. You will be prompted for your phone number (e.g. `+1234567890`).
2. Telegram sends a 5-digit verification code to your Telegram app.
3. Enter the code in your terminal.
4. If Two-Step Verification (2FA) is active on your account, enter your 2FA password.
5. The script verifies that the connected account is your **personal account** (not a bot).
6. It saves your session securely to `data/telegram_client.session` with `0600` permissions.
7. It prints your **Cloud StringSession (`TG_SESSION_STRING`)**. Save this if you plan to deploy to a cloud VPS later!

---

## 🏃 Running the Application

To start the local client:
```bash
./local/start.sh
```

To stop the client at any time, press `Ctrl+C`.

---

## 🧪 Testing

To run the automated test suite locally:
```bash
./local/test.sh
```
Or run non-destructive account connection verification:
```bash
source .venv/bin/activate
python3 scripts/check_connection.py
```

---

## ⚙️ Reply Modes & Commands

### 1. `REPLY_MODE=draft` (Default)
Incoming eligible messages will generate suggested drafts and log them to your console and database. **No messages are sent automatically.**

### 2. `REPLY_MODE=approval`
When an incoming eligible message arrives:
1. A draft is generated.
2. A notification is sent to your **Saved Messages** (private chat with yourself in Telegram):
   ```text
   📝 Pending Approval #1
   • Chat: Alice (123456789)
   • Incoming: "Hey, are you free?"
   • Suggested Reply: "Got your message, will get back shortly!"
   Send /approve 1 to send, or /reject 1 to discard.
   ```
3. You control the client directly from Telegram Saved Messages:
   - `/approve <id>` — Approves and sends the reply
   - `/reject <id>` — Discards the pending draft
   - `/pending` — Lists pending drafts
   - `/status` — Displays current mode, error count, and safety status
   - `/pause <duration>` — Snoozes auto-replies for a duration (e.g. `/pause 2h`, `/pause 30m`)
   - `/resume` — Resumes normal operations (clears pause & stop)
   - `/name <name>` — Customizes your personal name for the AI persona
   - `/prompt` — Displays the active system prompt
   - `/setprompt <text>` — Updates your AI persona instructions on the fly
   - `/stop` — Immediate emergency kill switch (halts all outgoing replies)

### 3. `REPLY_MODE=restricted_auto`
Allows automated replies without manual approval for allowlisted chats, **provided safety rules pass and explicit authorization is given**:
- You can toggle authorization at runtime inside Telegram Saved Messages by sending:
  ```text
  /auto on
  ```
- Or revoke anytime by sending:
  ```text
  /auto off
  ```

---

## 🔒 Session Security & Privacy

- **File Permissions**: The session file (`data/telegram_client.session`) is locked to user read/write only (`0600`).
- **Never Commit Credentials**: `.env` and `*.session` are excluded by `.gitignore`.
- **Revoking Access**: If you ever suspect a session is compromised, open Telegram:
  **Settings → Devices → Terminate Session**.

---

## 🛠️ Troubleshooting

- **Error: `Missing required configuration: TG_API_ID must be set.`**
  - Ensure you opened `.env` and replaced `your_api_id_here` with your actual numeric API ID from https://my.telegram.org/apps.
- **Error: `Connected account is a Bot account!`**
  - Telegram Bot API tokens are not supported; you must log in with your actual personal phone number.
- **Error: `ImportError: No module named 'telethon'`**
  - Run `./local/install.sh` to reinstall packages into `.venv`.
