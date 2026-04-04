import asyncio
import datetime
import json
import logging
import os
import random
from pathlib import Path

import discord
from discord import app_commands, ui
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
TARGET_USER_ID = int(os.environ["TARGET_USER_ID"])
MASTER_USER_ID = int(os.environ["MASTER_USER_ID"])
CHANNEL_ID = int(os.environ["CHANNEL_ID"])
DATA_DIR = Path(os.getenv("DATA_DIR", "."))
STATE_FILE = DATA_DIR / "state.json"

with open(Path(__file__).parent / "ping_messages.json") as _f:
    PING_MESSAGES = json.load(_f)

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
        "best_streak": 0,
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
        # stop/restart
        "paused": False,
        # lifetime stats
        "first_reminder_sent_iso": None,
        "total_reminders_sent": 0,
        "total_working": 0,
        "total_on_track": 0,
        "total_too_frequent": 0,
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
            state["best_streak"] = max(state.get("best_streak", 0), state["streak"])
            state["week_working"] = state.get("week_working", 0) + 1
            state["total_working"] = state.get("total_working", 0) + 1
            new_interval = random.uniform(1.5, 3.0)
            reply = (
                f"🔥 Love to hear it! Streak: **{state['streak']}** reminder(s) with progress.\n"
                f"Next reminder in ~{new_interval:.1f} days.\n"
                f"> Your goal: *{self.commitment.value}*"
            )
        else:  # on_track
            state["week_on_track"] = state.get("week_on_track", 0) + 1
            state["total_on_track"] = state.get("total_on_track", 0) + 1
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
        state["total_too_frequent"] = state.get("total_too_frequent", 0) + 1
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
    if state.get("paused"):
        logger.info("Reminder skipped — bot is paused.")
        return
    _reset_week_if_needed(state)
    state["week_reminders"] = state.get("week_reminders", 0) + 1
    state["total_reminders_sent"] = state.get("total_reminders_sent", 0) + 1
    if not state.get("first_reminder_sent_iso"):
        state["first_reminder_sent_iso"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

    parts = [f"<@{TARGET_USER_ID}> {random.choice(PING_MESSAGES)}"]

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

async def _sleep_interruptible(seconds: float, check_interval: float = 300.0) -> None:
    """Sleep for `seconds`, but wake up every `check_interval` seconds so the
    loop can notice a paused/stopped state change without waiting the full duration."""
    remaining = seconds
    while remaining > 0:
        await asyncio.sleep(min(remaining, check_interval))
        remaining -= check_interval


async def follow_up_loop():
    await client.wait_until_ready()
    while not client.is_closed():
        await asyncio.sleep(1800)  # check every 30 min

        state = load_state()
        if state.get("paused"):
            continue
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

        if state.get("paused"):
            await asyncio.sleep(300)  # check every 5 min while paused
            continue

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
            await _sleep_interruptible(wait)
            # Re-check paused state after waking up
            if load_state().get("paused"):
                continue

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


# ── Slash commands ─────────────────────────────────────────────────────────────

def _build_stats_embed(state: dict, title: str, color: discord.Color) -> discord.Embed:
    total = state.get("total_reminders_sent", 0)
    working = state.get("total_working", 0)
    on_track = state.get("total_on_track", 0)
    too_frequent = state.get("total_too_frequent", 0)
    ignored = max(0, total - working - on_track - too_frequent)
    responded = working + on_track + too_frequent
    response_rate = round(responded / total * 100) if total > 0 else 0

    first_iso = state.get("first_reminder_sent_iso")
    last_iso = state.get("last_reminder_sent_iso")

    embed = discord.Embed(title=title, color=color,
                          timestamp=datetime.datetime.now(datetime.timezone.utc))
    embed.add_field(name="Total reminders", value=str(total), inline=True)
    embed.add_field(name="Response rate", value=f"{response_rate}%", inline=True)
    embed.add_field(name="Best streak", value=f"🔥 {state.get('best_streak', 0)}", inline=True)
    embed.add_field(name="Working on it ✅", value=str(working), inline=True)
    embed.add_field(name="On track 👍", value=str(on_track), inline=True)
    embed.add_field(name="Too frequent 😅", value=str(too_frequent), inline=True)
    embed.add_field(name="Ignored 🙈", value=str(ignored), inline=True)

    if first_iso and last_iso:
        first_dt = datetime.datetime.fromisoformat(first_iso)
        last_dt = datetime.datetime.fromisoformat(last_iso)
        days = (last_dt - first_dt).days
        embed.add_field(
            name="Journey",
            value=f"{first_dt.strftime('%d %b %Y')} → {last_dt.strftime('%d %b %Y')} ({days} days)",
            inline=False,
        )

    return embed


# ── Bot startup ────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


@tree.command(name="done", description="Stop the thesis reminders and see your final stats.")
async def cmd_done(interaction: discord.Interaction):
    if interaction.user.id != TARGET_USER_ID:
        await interaction.response.send_message("This command isn't for you.", ephemeral=True)
        return

    state = load_state()
    if state.get("paused"):
        await interaction.response.send_message(
            "Reminders are already paused. Nothing to do.", ephemeral=True
        )
        return

    state["paused"] = True
    save_state(state)

    embed = _build_stats_embed(
        state,
        title="Thesis journey complete! 🎓",
        color=discord.Color.gold(),
    )
    embed.description = (
        "Reminders have been stopped. Congratulations on finishing your thesis!\n"
        f"*(If this was a mistake, <@{MASTER_USER_ID}> can restart with `/restart`.)*"
    )

    channel = await client.fetch_channel(CHANNEL_ID)
    await channel.send(
        f"<@{TARGET_USER_ID}> has stopped the thesis reminders. 🎉",
        embed=embed,
    )
    await interaction.response.send_message("Done! Reminders stopped. Stats posted in the channel.", ephemeral=True)
    logger.info("Bot paused by target user.")


@tree.command(name="restart", description="Re-enable thesis reminders for the target user.")
async def cmd_restart(interaction: discord.Interaction):
    if interaction.user.id != MASTER_USER_ID:
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return

    state = load_state()
    if not state.get("paused"):
        await interaction.response.send_message("Reminders are already running.", ephemeral=True)
        return

    state["paused"] = False
    next_send = _compute_next_send(state.get("current_interval_days", DEFAULT_INTERVAL))
    state["next_send_iso"] = next_send.isoformat()
    state["last_reminder_responded"] = True
    state["follow_up_sent"] = True
    save_state(state)

    channel = await client.fetch_channel(CHANNEL_ID)
    await channel.send(
        f"<@{TARGET_USER_ID}> Reminders are back on. "
        f"Next ping: **{next_send.strftime('%d %b %Y at %H:%M UTC')}**. "
        f"No escaping it. 😈"
    )
    await interaction.response.send_message(
        f"Done. Next reminder scheduled for {next_send.strftime('%d %b %Y at %H:%M UTC')}.",
        ephemeral=True,
    )
    logger.info("Bot restarted by master user.")


@tree.command(name="stats", description="Show current thesis reminder statistics.")
async def cmd_stats(interaction: discord.Interaction):
    if interaction.user.id not in (TARGET_USER_ID, MASTER_USER_ID):
        await interaction.response.send_message("This command isn't for you.", ephemeral=True)
        return

    state = load_state()
    paused_note = " *(paused)*" if state.get("paused") else ""
    embed = _build_stats_embed(
        state,
        title=f"Thesis reminder stats{paused_note}",
        color=discord.Color.blurple(),
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@client.event
async def on_ready():
    logger.info("Logged in as %s (id: %d)", client.user, client.user.id)
    client.add_view(ReminderView())  # re-register persistent view after restart
    await tree.sync()
    logger.info("Slash commands synced.")
    asyncio.ensure_future(reminder_loop())
    asyncio.ensure_future(weekly_summary_loop())
    asyncio.ensure_future(follow_up_loop())


client.run(DISCORD_TOKEN)
