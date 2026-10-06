import time
import discord
from discord.ext import commands, tasks

KEYWORD = "スーモ"
CHECK_INTERVAL_SEC = 5
COOLDOWN_SEC = 120

MESSAGE = (
    "あ❗️ スーモ❗️🌚ダン💥ダン💥ダン💥シャーン🎶"
    "スモ🌝スモ🌚スモ🌝スモ🌚スモ🌝スモ🌚ス〜〜〜モ⤴"
    "🌝スモ🌚スモ🌝スモ🌚スモ🌝スモ🌚スモ🌝ス〜〜〜モ⤵🌞"
)


class Sumo(commands.Cog):
    def __init__(self, bot: discord.Bot):
        self.bot = bot
        self.pending: set[int] = set()          # 発言待ちのチャンネルID
        self.last_sent: dict[int, float] = {}   # チャンネルID -> 最後に発言した時刻
        self.checker.start()

    def cog_unload(self):
        self.checker.cancel()

    def _in_cooldown(self, channel_id: int) -> bool:
        last = self.last_sent.get(channel_id)
        return last is not None and time.monotonic() - last < COOLDOWN_SEC

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return
        if KEYWORD not in message.channel.name:
            return
        if KEYWORD not in message.content:
            return
        if self._in_cooldown(message.channel.id):
            return
        self.pending.add(message.channel.id)

    @tasks.loop(seconds=CHECK_INTERVAL_SEC)
    async def checker(self):
        if not self.pending:
            return
        channel_ids = list(self.pending)
        self.pending.clear()
        for cid in channel_ids:
            if self._in_cooldown(cid):
                continue
            channel = self.bot.get_channel(cid)
            if channel is None:
                continue
            try:
                await channel.send(MESSAGE)
                self.last_sent[cid] = time.monotonic()
            except Exception as e:
                await self.bot.notify(e)

    @checker.before_loop
    async def _before_checker(self):
        await self.bot.wait_until_ready()


def setup(bot: discord.Bot):
    bot.add_cog(Sumo(bot))
