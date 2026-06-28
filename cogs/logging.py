import discord
from discord.ext import commands
from datetime import datetime, timezone
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import utils


def _embed(description, color, guild, author=None):
    e = discord.Embed(description=description, color=color,
                      timestamp=datetime.now(timezone.utc))
    e.set_footer(text=guild.name)
    if author:
        e.set_author(name=author.name, icon_url=author.display_avatar.url)
        e.set_thumbnail(url=author.display_avatar.url)
    return e


class Logging(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _send(self, guild, key, embed):
        cfg   = utils.get_config(str(guild.id))
        if not cfg.get("logs", {}).get(key, True):
            return
        ch_id = cfg.get("log_channel")
        if not ch_id:
            return
        ch = guild.get_channel(int(ch_id))
        if ch:
            await ch.send(embed=embed)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        desc = (
            f"**送信者** {message.author.mention}\n"
            f"**チャンネル** {message.channel.mention}\n"
            f"**内容**\n{message.content or '*(添付ファイルのみ)*'}"
        )
        await self._send(message.guild, "message_delete",
            _embed(desc, 0xE8383D, message.guild, message.author))

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if not before.guild or before.author.bot or before.content == after.content:
            return
        desc = (
            f"**送信者** {before.author.mention}  **チャンネル** {before.channel.mention}\n"
            f"**編集前**\n{before.content}\n"
            f"**編集後**\n{after.content}"
        )
        await self._send(before.guild, "message_edit",
            _embed(desc, 0xF0B132, before.guild, before.author))

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        desc = (
            f"{member.mention} がサーバーに参加しました\n"
            f"現在のメンバー数: **{member.guild.member_count}**"
        )
        await self._send(member.guild, "member_join",
            _embed(desc, 0x00A960, member.guild, member))

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        # Kick か Leave かを audit_log で判定
        kicked = False
        try:
            async for entry in member.guild.audit_logs(
                limit=1, action=discord.AuditLogAction.kick
            ):
                if entry.target.id == member.id:
                    kicked = True
                    await self._send(member.guild, "kick",
                        _embed(
                            f"{member.mention} がKickされました\n実行者: {entry.user.mention}",
                            0xE8383D, member.guild, member,
                        ))
        except discord.Forbidden:
            pass

        if not kicked:
            desc = (
                f"{member.mention} がサーバーから退出しました\n"
                f"現在のメンバー数: **{member.guild.member_count}**"
            )
            await self._send(member.guild, "member_leave",
                _embed(desc, 0xE8383D, member.guild, member))

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        await self._send(guild, "ban",
            _embed(f"{user.mention} がBANされました", 0xE8383D, guild, user))

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        # ロール変更
        for r in [r for r in after.roles if r not in before.roles]:
            await self._send(before.guild, "role_add",
                _embed(f"{after.mention} にロール {r.mention} が付与されました",
                       0x00A960, before.guild, after))
        for r in [r for r in before.roles if r not in after.roles]:
            await self._send(before.guild, "role_remove",
                _embed(f"{after.mention} からロール {r.mention} が削除されました",
                       0xE8383D, before.guild, after))

        # タイムアウト
        if not before.timed_out_until and after.timed_out_until:
            await self._send(before.guild, "timeout",
                _embed(
                    f"{after.mention} がタイムアウトされました\n"
                    f"解除: {discord.utils.format_dt(after.timed_out_until, 'R')}",
                    0xF0B132, before.guild, after,
                ))


def setup(bot):
    bot.add_cog(Logging(bot))
