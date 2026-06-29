import os, traceback, signal
from datetime import datetime, timezone
import discord
from dotenv import load_dotenv
from keep_alive import keep_alive

# SIGTERMを無視してbotを生かし続ける
signal.signal(signal.SIGTERM, signal.SIG_IGN)

load_dotenv()
TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = discord.Bot(intents=intents)


# ── イベント ──────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    if not hasattr(bot, "cogs_loaded"):
        for f in os.listdir("./cogs"):
            if f.endswith(".py") and not f.startswith("_"):
                try:
                    bot.load_extension(f"cogs.{f[:-3]}")
                    print(f"cog loaded: {f}")
                except Exception as e:
                    traceback.print_exc()
                    print(f"cog load error: {f} {e}")
        bot.cogs_loaded = True

        try:
            await bot.sync_commands()
            print("commands synced")
        except Exception as e:
            traceback.print_exc()
            print(f"command sync error: {e}")
            await _notify(e)  # 同期失敗を管理者にDMで知らせる

        # 起動/再起動の通知（初回のon_readyでのみ送信、同期の成否に関わらず送る）
        await _notify_startup()

    print(f"ready: {bot.user}")


@bot.event
async def on_application_command_error(ctx, error: Exception):
    await _notify(error, ctx=ctx)
    if ctx and not ctx.response.is_done():
        await ctx.respond("エラーが発生しました。", ephemeral=True)


# ── 起動通知 ──────────────────────────────────────────────────────────────────
async def _notify_startup():
    msg = (
        f"🟢 起動しました\n"
        f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC\n"
        f"user={bot.user}"
    )
    try:
        user = await bot.fetch_user(ADMIN_ID)
        await user.send(msg)
    except Exception:
        traceback.print_exc()


# ── エラー通知 ────────────────────────────────────────────────────────────────
async def _notify(error: Exception, ctx=None):
    header = [
        f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC",
        f"{type(error).__name__}: {error}",
    ]
    if ctx:
        header.append(f"guild={ctx.guild} channel={ctx.channel} user={ctx.user}")
    tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    msg = "\n".join(header) + "\n```" + tb[:1500] + "```"
    try:
        user = await bot.fetch_user(ADMIN_ID)
        await user.send(msg)
    except Exception:
        traceback.print_exc()


bot.notify = _notify

# ── 起動 ──────────────────────────────────────────────────────────────────────
keep_alive()
bot.run(TOKEN)
