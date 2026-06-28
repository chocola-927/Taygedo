import discord
from discord.ext import commands
from datetime import datetime, timezone
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import utils


class Welcome(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        cfg    = utils.get_config(str(member.guild.id))
        ch_id  = cfg.get("welcome_channel")
        if not ch_id:
            return
        ch = member.guild.get_channel(int(ch_id))
        if not ch:
            return

        embed = discord.Embed(
            description=(
                f"### {member.mention}さん、{member.guild.name}へようこそ！\n"
                f"現在のメンバー数: **{member.guild.member_count}**"
            ),
            color=0x00A960,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(name=member.name, icon_url=member.display_avatar.url)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=member.guild.name)
        await ch.send(embed=embed)


def setup(bot):
    bot.add_cog(Welcome(bot))
