import datetime
import logging
import os

import discord
from discord.ext import tasks
from dotenv import load_dotenv

load_dotenv()


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
TARGET_USER_ID = int(os.environ["TARGET_USER_ID"])
CHANNEL_ID = int(os.environ["CHANNEL_ID"])
REMINDER_HOUR = int(os.getenv("REMINDER_HOUR", "8"))
REMINDER_MINUTE = int(os.getenv("REMINDER_MINUTE", "0"))
REMINDER_MESSAGE = os.environ["REMINDER_MESSAGE"]

intents = discord.Intents.default()
client = discord.Client(intents=intents)

reminder_time = datetime.time(hour=REMINDER_HOUR, minute=REMINDER_MINUTE, tzinfo=datetime.timezone.utc)


@tasks.loop(time=reminder_time)
async def send_reminder():
    if datetime.datetime.now(datetime.timezone.utc).weekday() != 2:  # 2 = Wednesday
        return
    try:
        channel = await client.fetch_channel(CHANNEL_ID)
    except discord.NotFound:
        logger.error("Channel %d not found. Check CHANNEL_ID.", CHANNEL_ID)
        return
    except discord.Forbidden:
        logger.error("No permission to access channel %d.", CHANNEL_ID)
        return
    await channel.send(f"<@{TARGET_USER_ID}> {REMINDER_MESSAGE}")
    logger.info("Reminder sent to user %d in channel %d.", TARGET_USER_ID, CHANNEL_ID)


@client.event
async def on_ready():
    logger.info("Logged in as %s (id: %d)", client.user, client.user.id)
    if not send_reminder.is_running():
        send_reminder.start()
        logger.info(
            "Reminder scheduled weekly on Wednesdays at %02d:%02d UTC.",
            REMINDER_HOUR,
            REMINDER_MINUTE,
        )


client.run(DISCORD_TOKEN)
