# Domen Magistrska Reminder Bot

A Discord bot that reminds a specific user to work on their master's thesis. Reminders are adaptive, meaning the frequency adjusts based on the user's feedback, and the bot gets progressively cheekier if ignored.

## Features

- **Adaptive reminders** - sent every 1-5 days at a random time (09:00-17:00 UTC), with the interval adjusting based on user feedback
- **Interactive buttons** - each reminder has three response options:
  - ✅ Working on it - shortens the next interval, increments the streak
  - 👍 On track - keeps the current interval
  - 😅 Too frequent - extends the interval (capped at 5 days); shows a red warning after 3 consecutive dismissals without progress
- **Commitment tracking** - after clicking Working on it or On track, the user types what they'll do before the next reminder; this is quoted back at them next time
- **Streak counter** - tracks consecutive reminders where the user reported progress
- **Bonus challenges** - a random extra nudge appears in ~50% of reminders
- **Ignore detection** - if the user doesn't click any button within 24 hours, the bot sends a cheeky follow-up
- **Weekly summary** - posted every Monday at 09:00 UTC with stats for the week (reminders sent, responses, ignored count, streak)
- **Slash commands** - `/done` to stop reminders with a full stats recap, `/restart` to re-enable them, `/stats` to check progress at any time

## Project structure

```
bot.py              # Main bot code
requirements.txt    # Python dependencies
Dockerfile          # Container image definition
fly.toml            # Fly.io config (alternative deployment option)
.env                # Local environment variables (not committed)
```

## Environment variables

| Variable | Description |
|---|---|
| `DISCORD_TOKEN` | Bot token from the Discord Developer Portal |
| `TARGET_USER_ID` | Discord user ID of the person to remind |
| `MASTER_USER_IDS` | Comma-separated Discord user IDs of bot owners (can use `/restart`) |
| `CHANNEL_ID` | Discord channel ID where reminders are posted |
| `DATA_DIR` | Path to the persistent volume (set to `/data` in production) |

## Running locally

1. Fill in all values in `.env`
2. Install dependencies: `pip install -r requirements.txt`
3. Run: `python bot.py`

## Deploying to Azure Container Instances

The bot runs as a Docker container on Azure Container Instances (ACI) with state persisted to an Azure File Share.

### Azure resources

| Resource | Name |
|---|---|
| Resource group | `domen-bot-rg` |
| Storage account | `domenbotstore` |
| File share | `botdata` (mounted at `/data` in the container) |
| Container | `domen-bot` |
| Region | `italynorth` |
| Docker image | `hieronymusa/domen-bot:latest` (Docker Hub) |

### Deploying a new version

```bash
docker build -t hieronymusa/domen-bot:latest .
docker push hieronymusa/domen-bot:latest

az container delete --resource-group domen-bot-rg --name domen-bot --yes

az container create \
  --resource-group domen-bot-rg \
  --name domen-bot \
  --image hieronymusa/domen-bot:latest \
  --restart-policy Always \
  --cpu 0.5 \
  --memory 0.5 \
  --location italynorth \
  --os-type Linux \
  --environment-variables \
    TARGET_USER_ID=<TARGET_USER_ID> \
    MASTER_USER_IDS=<MASTER_USER_IDS> \
    CHANNEL_ID=<CHANNEL_ID> \
    DATA_DIR=/data \
  --secure-environment-variables \
    DISCORD_TOKEN=<DISCORD_TOKEN> \
  --azure-file-volume-account-name domenbotstore \
  --azure-file-volume-account-key <STORAGE_KEY> \
  --azure-file-volume-share-name botdata \
  --azure-file-volume-mount-path /data
```

### Useful management commands

```bash
# View logs
az container logs --resource-group domen-bot-rg --name domen-bot --follow

# Restart
az container restart --resource-group domen-bot-rg --name domen-bot

# Stop (to save credits)
az container stop --resource-group domen-bot-rg --name domen-bot

# Start
az container start --resource-group domen-bot-rg --name domen-bot
```

## Slash commands

| Command | Who can use it | What it does |
|---|---|---|
| `/done` | Target user only | Stops reminders and posts a full stats embed in the channel |
| `/restart` | Master users only | Re-enables reminders after they've been stopped |
| `/stats` | Both users | Shows current lifetime stats privately (ephemeral) |

> Slash commands are synced globally on bot startup. They may take up to an hour to appear in Discord after the first deploy.

## Persistent state

The bot stores all state in a single JSON file (`state.json`) on the Azure File Share mounted at `/data`. This file tracks the streak, current interval, weekly stats, scheduled send time, lifetime totals, and the user's last commitment. It survives container restarts and redeploys.
