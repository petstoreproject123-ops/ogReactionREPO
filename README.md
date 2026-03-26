# Telegram Reaction Bot System

A master bot that controls 7 worker bots to automatically react to every new post in your Telegram channel.

---

## How It Works

```
New Channel Post
       │
  Master Bot detects it
       │
  Dispatches all 7 Worker Bots (with staggered delays)
       │
  Each worker picks a random reaction from your pool
  and reacts to the post independently
```

---

## Setup

### Step 1 — Create all 8 bots via @BotFather

1. Open Telegram and search for `@BotFather`
2. Send `/newbot` and follow the steps to create **8 bots** (1 master + 7 workers)
3. Save all 8 tokens — you'll need them in the next step

### Step 2 — Add all 8 bots as admins to your channel

1. Open your Telegram channel settings
2. Go to **Administrators → Add Administrator**
3. Search each bot by username and add it
4. Give each bot at least the **Post Messages** permission

### Step 3 — Configure `config.json`

Open `config.json` and fill in your values:

```json
{
  "master_token": "1234567890:ABCDefgh...",
  "worker_tokens": [
    "BOT_1_TOKEN",
    "BOT_2_TOKEN",
    "BOT_3_TOKEN",
    "BOT_4_TOKEN",
    "BOT_5_TOKEN",
    "BOT_6_TOKEN",
    "BOT_7_TOKEN"
  ],
  "channel_id": "@yourchannel",
  "owner_id": 123456789,
  "reactions": ["👍", "🔥", "❤️", "😂", "🎉", "👏", "💯"]
}
```

> **How to find your `owner_id`:** Message `@userinfobot` on Telegram — it will reply with your numeric user ID.

> **`channel_id`** can be either `@username` format or the numeric channel ID (e.g. `-1001234567890`).

### Step 4 — Install dependencies

```bash
pip install -r requirements.txt
```

### Step 5 — Run

```bash
python main.py
```

---

## Commands (owner only)

| Command | Description |
|---|---|
| `/start` | Show help and available commands |
| `/setreactions 👍 🔥 ❤️` | Update the reaction pool |
| `/listreactions` | View current reaction pool |
| `/status` | Check which worker bots are online |

> All commands only work when sent by the owner (matched by `owner_id` in config).

---

## File Structure

```
reaction_bot_system/
├── main.py           # Entry point — run this
├── master_bot.py     # Master bot logic + command handlers
├── worker_bot.py     # Worker bot class
├── config.json       # Tokens, channel ID, owner ID, reaction pool
├── requirements.txt  # Python dependencies
└── README.md         # This file
```

---

## Notes

- **Staggered delays:** Workers react 1–3 seconds apart to look natural
- **Crash safety:** If one worker fails, the others continue unaffected
- **Persistent config:** Reaction pool changes via `/setreactions` are saved to `config.json` and survive restarts
- **Telegram limit:** Each bot can only place one reaction per message — this system uses 7 separate bots to place 7 reactions
