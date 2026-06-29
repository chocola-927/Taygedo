import os, traceback, signal
from datetime import datetime, timezone
import discord
from dotenv import load_dotenv
from keep_alive import keep_alive

# SIGTERMを無視してbotを生かし続ける
signal.signal(signal.SIGTERM, signal.SIG_IGN)

load_dotenv()
TOKEN    = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = discord.Bot(intents=intents)


# ── cogロード（起動時に一度だけ実行） ────────────────────────────────────────

async def setup_hook():
    for f in os.listdir("./cogs"):
        if f.endswith(".py") and not f.startswith("_"):
            try:
                bot.load_extension(f"cogs.{f[:-3]}")
                print(f"cog loaded: {f}")
            except Exception as e:
                traceback.print_exc()
                print(f"cog load error: {f} {e}")

bot.setup_hook = setup_hook


# ── イベント ──────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    await bot.sync_commands()
    print(f"commands synced")
    print(f"ready: {bot.user}")


@bot.event
async def on_application_command_error(ctx, error: Exception):
    await _notify(error, ctx=ctx)
    if ctx and not ctx.response.is_done():
        await ctx.respond("エラーが発生しました。", ephemeral=True)


# ── エラー通知 ────────────────────────────────────────────────────────────────

async def _notify(error: Exception, ctx=None):
    header = [
        f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC",
        f"{type(error).__name__}: {error}",
    ]
    if ctx:
        header.append(f"guild={ctx.guild} channel={ctx.channel} user={ctx.user}")
    tb  = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    msg = "\n".join(header) + "\n```" + tb[:1500] + "```"
    try:
        user = await bot.fetch_user(ADMIN_ID)
        await user.send(msg)
    except Exception:
        traceback.print_exc()

bot.notify = _notify


# ── 起動 ──────────────────────────────────────────────────────────────────────

keep_alive()
while True:
    try:
        bot.run(TOKEN)
    except Exception as e:
        traceback.print_exc()
        print(f"bot crashed: {e}, restarting...")
        import time
        time.sleep(5)
    print("bot.run exited, restarting...")
    import time
    time.sleep(5)
