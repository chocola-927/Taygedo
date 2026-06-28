import os, traceback
from datetime import datetime, timezone

import discord
from dotenv import load_dotenv
from keep_alive import keep_alive

load_dotenv()
TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = discord.Bot(intents=intents)


@bot.event
async def on_ready():
    if not hasattr(bot, "cogs_loaded"):
        for f in os.listdir("./cogs"):
            if f.endswith(".py") and not f.startswith("_"):
                try:
                    bot.load_extension(f"cogs.{f[:-3]}")
                except Exception as e:
                    print(f"cog load error: {f} {e}")
        bot.cogs_loaded = True

    await bot.sync_commands()
    print(f"ready: {bot.user}")


@bot.event
async def on_application_command_error(ctx, error: Exception):
    await _notify(error, ctx=ctx)
    if ctx and not ctx.response.is_done():
        await ctx.respond("エラー発生", ephemeral=True)


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
keep_alive()
bot.run(TOKEN)
