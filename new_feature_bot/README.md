# New Feature Bot

This project is a Telegram code router built with Telethon.

It does three things:

1. Read incoming messages and extract one or more pickup codes
2. Route each code to a different target bot based on its prefix
3. Forward the returned messages to another Telegram group

## Why Telethon

This project uses a Telegram user session, not the Bot API.

That is intentional: the router needs to send messages to other bots and wait for their replies.

## Features

- Multiple codes in one message
- Prefix-based routing
- Forward bot replies to another group
- Configurable code regex
- Configurable source chats
- Summary notices before forwarding

## Project Structure

```text
new_feature_bot/
├─ app.py
├─ requirements.txt
├─ .env.example
├─ README.md
└─ code_router_bot/
   ├─ __init__.py
   ├─ config.py
   ├─ parser.py
   ├─ router.py
   └─ main.py
```

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env`.

## Environment

```env
API_ID=12345678
API_HASH=replace-with-your-api-hash
PHONE_NUMBER=+8613800000000
TWO_FA_PASSWORD=
STRING_SESSION=
SESSION_NAME=data/router_session
LISTEN_CHAT_IDS=
FORWARD_CHAT=@your_target_group
ROUTES_JSON={"ABC":"@bot_a","XYZ":"@bot_b"}
CODE_REGEX=\b([A-Za-z]{1,10}(?:[-_:|][A-Za-z0-9]{4,64}|[A-Za-z0-9]{4,64}\d[A-Za-z0-9]{0,64}))\b
REQUEST_TIMEOUT=90
RESPONSE_IDLE_TIMEOUT=5
FORWARD_SUMMARY=true
LOG_LEVEL=INFO
```

## Notes About Config

- `PHONE_NUMBER` is used for first-time interactive login
- `STRING_SESSION` can replace local session files for deployment
- `LISTEN_CHAT_IDS` is optional and can be a comma-separated list such as `123456789,@source_group`
- `FORWARD_CHAT` is the group or channel that receives forwarded results
- `ROUTES_JSON` maps prefixes to target bots
- `CODE_REGEX` should be adjusted if your pickup codes have a stricter format

## Run

```bash
python app.py
```

On the first run, Telethon may ask for:

- login code
- two-factor password

## Example Route

If the incoming message contains:

```text
ABC-12345 XYZ-99887
```

And:

```json
{"ABC":"@bot_a","XYZ":"@bot_b"}
```

Then the router will:

1. Send `ABC-12345` to `@bot_a`
2. Send `XYZ-99887` to `@bot_b`
3. Forward both returned results to `FORWARD_CHAT`
