# Domen Magistrska Reminder Bot

A Discord bot that reminds a specific user to work on their master's thesis. Reminders are adaptive — the frequency adjusts based on the user's feedback, and the bot gets progressively cheekier if ignored.

## Features

- **Adaptive reminders** — sent every 1–5 days at a random time (09:00–17:00 UTC), with the interval adjusting based on user feedback
- **Interactive buttons** — each reminder has three response options:
  - ✅ Working on it — shortens the next interval, increments the streak
  - 👍 On track — keeps the current interval
  - 😅 Too frequent — extends the interval (capped at 5 days); shows a red warning after 3 consecutive dismissals without progress
- **Commitment tracking** — after clicking Working on it or On track, the user types what they'll do before the next reminder; this is quoted back at them next time
- **Streak counter** — tracks consecutive reminders where the user reported progress
- **Bonus challenges** — a random extra nudge appears in ~50% of reminders
- **Ignore detection** — if the user doesn't click any button within 24 hours, the bot sends a cheeky follow-up
- **Weekly summary** — posted every Monday at 09:00 UTC with stats for the week (reminders sent, responses, ignored count, streak)
- **Slash commands** — `/done` to stop reminders with a full stats recap, `/restart` to re-enable them, `/stats` to check progress at any time

## Project structure

```
bot.py              # Main bot code
requirements.txt    # Python dependencies
Dockerfile          # Container definition for Railway
.env                # Local environment variables (not committed)
```

## Environment variables

| Variable | Description |
|---|---|
| `DISCORD_TOKEN` | Bot token from the Discord Developer Portal |
| `TARGET_USER_ID` | Discord user ID of the person to remind |
| `MASTER_USER_ID` | Discord user ID of the bot owner (can restart reminders with `/restart`) |
| `CHANNEL_ID` | Discord channel ID where reminders are posted |
| `REMINDER_MESSAGE` | The base reminder message text |
| `DATA_DIR` | Path to the persistent volume (set to `/data` on Railway) |

## Running locally

1. Copy `.env` and fill in all values including `MASTER_USER_ID`
2. Install dependencies: `pip install -r requirements.txt`
3. Run: `python bot.py`

## Deploying to Railway

1. Push the repo to GitHub and connect it to a Railway project
2. Add all environment variables in the Railway service Variables tab (including `MASTER_USER_ID`)
3. Add a Railway Volume mounted at `/data` and set `DATA_DIR=/data`
4. Click Deploy

## Slash commands

| Command | Who can use it | What it does |
|---|---|---|
| `/done` | Target user only | Stops reminders and posts a full stats embed in the channel |
| `/restart` | Master user only | Re-enables reminders after they've been stopped |
| `/stats` | Both users | Shows current lifetime stats privately (ephemeral) |

> Slash commands are synced globally on bot startup. They may take up to an hour to appear in Discord after the first deploy.

## Persistent state

The bot stores all state in a single JSON file (`state.json`) on the Railway Volume. This file tracks the streak, current interval, weekly stats, scheduled send time, lifetime totals, and the user's last commitment. It survives redeploys.
