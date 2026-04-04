import asyncio
import datetime
import json
import logging
import os
import random
from pathlib import Path

import discord
from discord import ui
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
TARGET_USER_ID = int(os.environ["TARGET_USER_ID"])
CHANNEL_ID = int(os.environ["CHANNEL_ID"])
REMINDER_MESSAGE = os.environ["REMINDER_MESSAGE"]
DATA_DIR = Path(os.getenv("DATA_DIR", "."))
STATE_FILE = DATA_DIR / "state.json"

MIN_INTERVAL = 1.0    # days
MAX_INTERVAL = 5.0    # days
DEFAULT_INTERVAL = 3.0
SEND_HOUR_MIN = 9     # UTC (= 11 CET / 12 CEST)
SEND_HOUR_MAX = 17    # UTC (= 19 CET / 20 CEST)

BONUS_CHALLENGES = [
    "Write just one sentence in your thesis today. Just one.",
    "Open your thesis and read what you wrote last time.",
    "Write a 3-bullet outline for the next section you need to tackle.",
    "Find and read one paper related to your topic.",
    "Set a 25-minute timer and write without stopping.",
    "Message your supervisor with a progress update.",
    "Write the abstract — even a rough draft counts.",
    "Identify the ONE thing blocking you and write it down.",
    "Review your methodology section for 15 minutes.",
    "Write down 3 things you've already accomplished in your thesis.",
    "Pick the easiest thing on your thesis to-do list and do it now.",
    "Write one paragraph you've been avoiding.",
]

FOLLOW_UP_MESSAGES = [
    "👀 Helloooo? I sent you a reminder over 24 hours ago. Just gonna leave that there.",
    "Still ignoring me, huh? Bold strategy. Thesis not writing itself though.",
    "I know you saw it. The little checkmark doesn't lie. 😐",
    "Friendly reminder that I am, in fact, still here. And so is your thesis.",
    "Oh don't mind me, I'm just a bot you've been ghosting for a day. No big deal.",
    "24 hours. No response. Your thesis has been open 0 times. Allegedly.",
    "Knocking knocking 🚪 ... it's your thesis. It misses you.",
]


# ── State ─────────────────────────────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return _default_state()


def save_state(state: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def _default_state() -> dict:
    return {
        "streak": 0,
        "current_interval_days": DEFAULT_INTERVAL,
        "too_frequent_streak": 0,
        "pending_commitment": None,
        "next_send_iso": None,
        "last_weekly_summary_date": None,
        "week_start": None,
        "week_reminders": 0,
        "week_working": 0,
        "week_on_track": 0,
        "week_too_frequent": 0,
        "last_reminder_sent_iso": None,
        "last_reminder_responded": True,
        "follow_up_sent": True,
    }


def _reset_week_if_needed(state: dict) -> None:
    today = datetime.date.today()
    week_start = datetime.date.fromisoformat(state["week_start"]) if state.get("week_start") else None
    if week_start is None or (today - week_start).days >= 7:
        state.update({
            "week_start": today.isoformat(),
            "week_reminders": 0,
            "week_working": 0,
            "week_on_track": 0,
            "week_too_frequent": 0,
        })


def _compute_next_send(interval_days: float) -> datetime.datetime:
    now = datetime.datetime.now(datetime.timezone.utc)
    jitter = random.uniform(-0.3, 0.3)
    base = now + datetime.timedelta(days=interval_days + jitter)
    return base.replace(
        hour=random.randint(SEND_HOUR_MIN, SEND_HOUR_MAX),
        minute=random.randint(0, 59),
        second=0,
        microsecond=0,
    )


# ── Discord UI ─────────────────────────────────────────────────────────────────

class CommitmentModal(ui.Modal, title="Accountability check"):
    commitment = ui.TextInput(
        label="What will you work on before the next reminder?",
        placeholder="e.g. Write the introduction section...",
        required=True,
        max_length=200,
    )

    def __init__(self, response_type: str):
        super().__init__()
        self.response_type = response_type

    async def on_submit(self, interaction: discord.Interaction):
        state = load_state()
        state["pending_commitment"] = self.commitment.value
        state["too_frequent_streak"] = 0
        state["last_reminder_responded"] = True

        if self.response_type == "working":
            state["streak"] = state.get("streak", 0) + 1
            state["week_working"] = state.get("week_working", 0) + 1
            new_interval = random.uniform(1.5, 3.0)
            reply = (
                f"🔥 Love to hear it! Streak: **{state['streak']}** reminder(s) with progress.\n"
                f"Next reminder in ~{new_interval:.1f} days.\n"
                f"> Your goal: *{self.commitment.value}*"
            )
        else:  # on_track
            state["week_on_track"] = state.get("week_on_track", 0) + 1
            new_interval = random.uniform(2.0, 4.0)
            reply = (
                f"👍 Good to know. Next reminder in ~{new_interval:.1f} days.\n"
                f"> Your goal: *{self.commitment.value}*"
            )

        state["current_interval_days"] = new_interval
        next_send = _compute_next_send(new_interval)
        state["next_send_iso"] = next_send.isoformat()
        save_state(state)

        await interaction.response.send_message(reply, ephemeral=True)
        try:
            await interaction.message.edit(view=None)
        except Exception:
            pass


class ReminderView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def _check_user(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != TARGET_USER_ID:
            await interaction.response.send_message("This reminder isn't for you!", ephemeral=True)
            return False
        return True

    @ui.button(label="Working on it! ✅", style=discord.ButtonStyle.success, custom_id="reminder:working")
    async def working(self, interaction: discord.Interaction, button: ui.Button):
        if not await self._check_user(interaction):
            return
        await interaction.response.send_modal(CommitmentModal("working"))

    @ui.button(label="On track 👍", style=discord.ButtonStyle.primary, custom_id="reminder:on_track")
    async def on_track(self, interaction: discord.Interaction, button: ui.Button):
        if not await self._check_user(interaction):
            return
        await interaction.response.send_modal(CommitmentModal("on_track"))

    @ui.button(label="Too frequent 😅", style=discord.ButtonStyle.secondary, custom_id="reminder:too_frequent")
    async def too_frequent(self, interaction: discord.Interaction, button: ui.Button):
        if not await self._check_user(interaction):
            return

        state = load_state()
        state["too_frequent_streak"] = state.get("too_frequent_streak", 0) + 1
        state["week_too_frequent"] = state.get("week_too_frequent", 0) + 1
        state["last_reminder_responded"] = True

        new_interval = min(
            state.get("current_interval_days", DEFAULT_INTERVAL) + random.uniform(0.5, 1.5),
            MAX_INTERVAL,
        )
        state["current_interval_days"] = new_interval
        state["next_send_iso"] = _compute_next_send(new_interval).isoformat()
        save_state(state)

        tf_streak = state["too_frequent_streak"]
        if tf_streak >= 3:
            embed = discord.Embed(
                title="⚠️ Really?",
                description=(
                    f"You've said 'too frequent' **{tf_streak} times in a row** "
                    f"without reporting any progress.\n\n"
                    f"Your thesis won't write itself.\n"
                    f"Next reminder in ~{new_interval:.1f} days — but it's not going away."
                ),
                color=discord.Color.red(),
            )
            embed.set_footer(text=f"Streak: {state.get('streak', 0)} | Interval: {new_interval:.1f}d")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(
                f"Ok, got it. Next reminder in ~{new_interval:.1f} days.",
                ephemeral=True,
            )

        try:
            await interaction.message.edit(view=None)
        except Exception:
            pass


# ── Reminder & summary sending ─────────────────────────────────────────────────

async def send_reminder():
    state = load_state()
    _reset_week_if_needed(state)
    state["week_reminders"] = state.get("week_reminders", 0) + 1

    parts = [f"<@{TARGET_USER_ID}> {REMINDER_MESSAGE}"]

    if state.get("pending_commitment"):
        parts.append(f'\n> Last time you said you\'d: *{state["pending_commitment"]}*\nDid you?')

    streak = state.get("streak", 0)
    if streak > 0:
        parts.append(f"\n🔥 Current streak: **{streak}** reminder(s) with reported progress!")

    if random.random() < 0.5:
        parts.append(f"\n**Bonus challenge:** {random.choice(BONUS_CHALLENGES)}")

    channel = await client.fetch_channel(CHANNEL_ID)
    await channel.send("\n".join(parts), view=ReminderView())

    state["last_reminder_sent_iso"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    state["last_reminder_responded"] = False
    state["follow_up_sent"] = False
    save_state(state)
    logger.info("Reminder sent.")


async def send_weekly_summary():
    state = load_state()
    channel = await client.fetch_channel(CHANNEL_ID)

    ignored = max(
        0,
        state.get("week_reminders", 0)
        - state.get("week_working", 0)
        - state.get("week_on_track", 0)
        - state.get("week_too_frequent", 0),
    )

    color = discord.Color.green() if state.get("week_working", 0) > 0 else discord.Color.orange()
    embed = discord.Embed(
        title="📊 Weekly Thesis Progress Summary",
        color=color,
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    embed.add_field(name="Reminders sent", value=str(state.get("week_reminders", 0)), inline=True)
    embed.add_field(name="Working on it ✅", value=str(state.get("week_working", 0)), inline=True)
    embed.add_field(name="On track 👍", value=str(state.get("week_on_track", 0)), inline=True)
    embed.add_field(name="Too frequent 😅", value=str(state.get("week_too_frequent", 0)), inline=True)
    embed.add_field(name="Ignored 🙈", value=str(ignored), inline=True)
    embed.add_field(name="Streak 🔥", value=str(state.get("streak", 0)), inline=True)
    if state.get("pending_commitment"):
        embed.add_field(name="Current commitment", value=f'*{state["pending_commitment"]}*', inline=False)

    await channel.send(f"<@{TARGET_USER_ID}>", embed=embed)

    state["last_weekly_summary_date"] = datetime.date.today().isoformat()
    save_state(state)
    logger.info("Weekly summary sent.")


# ── Background loops ───────────────────────────────────────────────────────────

async def follow_up_loop():
    await client.wait_until_ready()
    while not client.is_closed():
        await asyncio.sleep(1800)  # check every 30 min

        state = load_state()
        if state.get("last_reminder_responded", True) or state.get("follow_up_sent", True):
            continue

        sent_iso = state.get("last_reminder_sent_iso")
        if not sent_iso:
            continue

        sent_at = datetime.datetime.fromisoformat(sent_iso)
        hours_since = (datetime.datetime.now(datetime.timezone.utc) - sent_at).total_seconds() / 3600

        if hours_since >= 24:
            channel = await client.fetch_channel(CHANNEL_ID)
            await channel.send(f"<@{TARGET_USER_ID}> {random.choice(FOLLOW_UP_MESSAGES)}")
            state["follow_up_sent"] = True
            save_state(state)
            logger.info("Follow-up sent after %.1f hours of silence.", hours_since)


async def reminder_loop():
    await client.wait_until_ready()
    while not client.is_closed():
        state = load_state()
        next_send_iso = state.get("next_send_iso")

        if next_send_iso:
            next_send = datetime.datetime.fromisoformat(next_send_iso)
        else:
            next_send = _compute_next_send(state.get("current_interval_days", DEFAULT_INTERVAL))
            state["next_send_iso"] = next_send.isoformat()
            save_state(state)

        now = datetime.datetime.now(datetime.timezone.utc)
        wait = (next_send - now).total_seconds()

        if wait > 0:
            logger.info("Next reminder at %s UTC (in %.1f h).", next_send.strftime("%Y-%m-%d %H:%M"), wait / 3600)
            await asyncio.sleep(wait)

        await send_reminder()

        state = load_state()
        next_send = _compute_next_send(state.get("current_interval_days", DEFAULT_INTERVAL))
        state["next_send_iso"] = next_send.isoformat()
        save_state(state)


async def weekly_summary_loop():
    await client.wait_until_ready()
    while not client.is_closed():
        await asyncio.sleep(1800)  # check every 30 min

        now = datetime.datetime.now(datetime.timezone.utc)
        today = now.date()

        # Send on Mondays between 09:00–10:00 UTC
        if today.weekday() != 0 or not (9 <= now.hour < 10):
            continue

        state = load_state()
        last = state.get("last_weekly_summary_date")
        if last:
            last_date = datetime.date.fromisoformat(last)
            if last_date.isocalendar().week == today.isocalendar().week:
                continue  # already sent this week

        await send_weekly_summary()


# ── Bot startup ────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
client = discord.Client(intents=intents)


@client.event
async def on_ready():
    logger.info("Logged in as %s (id: %d)", client.user, client.user.id)
    client.add_view(ReminderView())  # re-register persistent view after restart
    asyncio.ensure_future(reminder_loop())
    asyncio.ensure_future(weekly_summary_loop())
    asyncio.ensure_future(follow_up_loop())


client.run(DISCORD_TOKEN)
