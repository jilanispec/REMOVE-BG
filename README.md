# Python Telegram Background Remover (Vercel)

A stateless Telegram bot that accepts images and returns PNG files with transparent backgrounds. It uses Telegram webhooks, Vercel Python Functions, and the remove.bg API.

**No database. No `users.json`. No user accounts or persistent image storage.**

## Project layout

```text
.
├── api/
│   └── webhook.py
├── .env.example
├── .gitignore
├── requirements.txt
├── vercel.json
└── README.md
```

## Requirements

- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- A remove.bg API key from [remove.bg API](https://www.remove.bg/api)
- A Vercel account and a Git repository
- A Vercel plan/function duration that can accommodate the external image API request

## 1. Configure environment variables

In Vercel → Project → Settings → Environment Variables, add:

- `TELEGRAM_BOT_TOKEN` — token from BotFather
- `REMOVEBG_API_KEY` — remove.bg API key
- `TELEGRAM_WEBHOOK_SECRET` — long random secret using letters, digits, `_` or `-`

Do not commit `.env` or place secrets in frontend code. `.env.example` is only a template.

To generate a webhook secret locally with Python:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32).replace('-', 'a').replace('_', 'b'))"
```

If you generate a secret with characters outside Telegram's allowed set, regenerate it using a restricted alphabet, for example:

```bash
python -c "import secrets,string; print(''.join(secrets.choice(string.ascii_letters + string.digits + '_-') for _ in range(48)))"
```

## 2. Deploy to Vercel

1. Put these files in a GitHub repository.
2. In Vercel, choose **Add New → Project** and import that repository.
3. Add the three environment variables before deploying.
4. Deploy the project.
5. Copy the deployed HTTPS domain, for example `https://your-project.vercel.app`.
6. Open `https://your-project.vercel.app/api/webhook` in a browser. It should return a small JSON health response.

`vercel.json` requests a 60-second maximum function duration. The actual maximum is subject to your Vercel plan and current platform limits. If your plan does not permit 60 seconds, change the setting to a duration allowed by your plan. Image processing may time out on plans with short execution limits.

## 3. Register the Telegram webhook

After deployment, run the following from a terminal. Replace the three placeholder values with the same values configured in Vercel.

### macOS / Linux / Git Bash

```bash
export TELEGRAM_BOT_TOKEN='your_bot_token'
export TELEGRAM_WEBHOOK_SECRET='your_webhook_secret'
export VERCEL_URL='https://your-project.vercel.app'

curl -sS -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
  --data-urlencode "url=${VERCEL_URL}/api/webhook" \
  --data-urlencode "secret_token=${TELEGRAM_WEBHOOK_SECRET}" \
  --data-urlencode 'allowed_updates=["message","edited_message"]'
```

Telegram should return `{"ok":true,...}`. Keep your bot token private.

Check the webhook status:

```bash
curl -sS "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getWebhookInfo"
```

If you change `TELEGRAM_WEBHOOK_SECRET`, update it in Vercel, redeploy, and call `setWebhook` again with the new secret.

## 4. Use the bot

Open the bot in Telegram, press **Start**, then send a photo or an image document. The bot replies with a PNG file whose background has been removed.

## Supported behavior

- Telegram photos and image documents
- PNG output with transparency
- `/start` and `/help`
- 10 MB application-level image limit
- No user profiles, usage history, or permanent image storage
- Webhook authentication with Telegram's secret-token header

## Important limits and privacy notes

- This is a synchronous webhook: Vercel keeps the function running while Telegram's image is downloaded, remove.bg processes it, and the result is uploaded back to Telegram. If this exceeds the allowed function duration, Telegram may retry the update and users may receive duplicate replies. For a production bot with slower processing, use a queue/worker on a host designed for background jobs.
- remove.bg has its own pricing, supported image limits, and API quota. Check its current terms and limits before launch.
- Telegram and remove.bg necessarily handle the images. “No storage” here means this code does not write images or user records to a database or local persistent file; it cannot promise that third-party services retain no data under their own policies.
- The function does not keep a user database or enforce per-user quotas. A public bot can be abused and API credits can be consumed. Consider provider-side spending limits and platform-level rate limiting before sharing it widely.
- Telegram may retry webhook deliveries after errors/timeouts. This minimal stateless version does not persist update IDs, so it cannot guarantee exactly-once processing.
- Only use images you have permission to process.

## Local syntax check

This project targets Vercel's Python Function runtime. To check syntax locally:

```bash
python -m py_compile api/webhook.py
```

You can deploy directly to Vercel; local webhook testing requires a public HTTPS tunnel and the same environment variables.
