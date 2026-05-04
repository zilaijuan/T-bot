# Telegram File Code Bot

Telegram bot and web uploader for sharing files by pickup code.

## Features

- Single file upload from Telegram: send a file, get a code back
- Multi-file bundle: one code can point to multiple files
- Expiring codes and permanent codes
- Admin statistics command
- Built-in web upload page
- Deep link support: `https://t.me/<bot_username>?start=<code>`
- SQLite storage

## Commands

- `/start`
- `/help`
- `/new 7d`
- `/new forever`
- `/done`
- `/cancel`
- `/stats`

## Upload Flow

### Telegram single file

1. Send a photo, video, or document to the bot
2. The bot saves it and returns a pickup code
3. Anyone can send the code to the bot to receive the file back

### Telegram multi-file bundle

1. Send `/new 7d` or `/new forever`
2. Send multiple files
3. Send `/done`
4. The bot returns one code for the whole bundle

### Web upload

1. Open the web page
2. Upload multiple files
3. Set expiry like `30m`, `12h`, `7d`, `4w`, or `forever`
4. Submit and get one shared code

## Environment

Create a `.env` file:

```env
BOT_TOKEN=123456:replace-with-your-bot-token
DATABASE_PATH=data/bot.db
UPLOAD_DIR=data/uploads
CODE_LENGTH=8
DEFAULT_EXPIRY=forever
ADMIN_USER_IDS=123456789,987654321
WEB_ENABLED=true
WEB_HOST=127.0.0.1
WEB_PORT=8080
PUBLIC_BASE_URL=
```

## Install

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Run

```bash
python app.py
```

## Docker Deploy

1. Create `.env` from `.env.example`
2. Fill at least `BOT_TOKEN`
3. Start the container:

```bash
docker compose up -d --build
```

4. Check logs:

```bash
docker compose logs -f
```

5. Stop:

```bash
docker compose down
```

### Docker Notes

- The bot and web uploader run in the same container
- Web uploader is exposed on `http://localhost:${WEB_PORT}`
- Data is persisted to `./data`
- In Docker, `WEB_HOST` is forced to `0.0.0.0`
- If you use a public domain, set `PUBLIC_BASE_URL`

## Notes

- Telegram-uploaded files are reused by `file_id`
- Web-uploaded files are stored under `UPLOAD_DIR`
- Expired bundles stay in the database but cannot be redeemed
- The current runtime uses polling for the bot and a built-in Flask web server
