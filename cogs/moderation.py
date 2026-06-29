import discord
from discord.ext import commands
from datetime import datetime, timezone, timedelta
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import utils


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _log(self, guild, key, description, color, user=None):
        cfg   = utils.get_config(str(guild.id))
        if not cfg.get("logs", {}).get(key, True):
            return
        ch_id = cfg.get("log_channel")
        if not ch_id:
            return
        ch = guild.get_channel(int(ch_id))
        if not ch:
            return
        e = discord.Embed(description=description, color=color,
                          timestamp=datetime.now(timezone.utc))
        if user:
            e.set_author(name=user.name, icon_url=user.display_avatar.url)
        e.set_footer(text=guild.name)
        await ch.send(embed=e)

    @discord.slash_command(description="ユーザーをBANします")
    @discord.default_permissions(ban_members=True)
    async def ban(self, ctx: discord.ApplicationContext,
                  user: discord.Option(discord.Member, "対象ユーザー"),
                  reason: discord.Option(str, "理由", required=False)):
        await user.ban(reason=reason)
        await ctx.respond(f"{user.mention} をBANしました。", ephemeral=True)
        await self._log(ctx.guild, "ban",
            f"{user.mention} がBANされました\n理由: {reason or 'なし'}\n実行者: {ctx.user.mention}",
            0xE8383D, user)

    @discord.slash_command(description="ユーザーをKickします")
    @discord.default_permissions(kick_members=True)
    async def kick(self, ctx: discord.ApplicationContext,
                   user: discord.Option(discord.Member, "対象ユーザー"),
                   reason: discord.Option(str, "理由", required=False)):
        # kick前にuser情報を保持（kick後はguildから消えるため）
        user_id   = user.id
        user_name = user.name

        await user.kick(reason=reason)
        await ctx.respond(f"{user.mention} をKickしました。", ephemeral=True)

        # logging.py の on_member_remove と二重にならないよう
        # bot にフラグを立てて logging 側でスキップさせる
        if not hasattr(self.bot, "_kicked_users"):
            self.bot._kicked_users = set()
        self.bot._kicked_users.add(user_id)

        await self._log(ctx.guild, "kick",
            f"<@{user_id}> がKickされました\n理由: {reason or 'なし'}\n実行者: {ctx.user.mention}",
            0xE8383D, None)

    @discord.slash_command(description="ユーザーをタイムアウトします")
    @discord.default_permissions(moderate_members=True)
    async def timeout(self, ctx: discord.ApplicationContext,
                      user: discord.Option(discord.Member, "対象ユーザー"),
                      minutes: discord.Option(int, "分数"),
                      reason: discord.Option(str, "理由", required=False)):
        await user.timeout_for(timedelta(minutes=minutes), reason=reason)
        await ctx.respond(f"{user.mention} を {minutes} 分タイムアウトしました。", ephemeral=True)
        await self._log(ctx.guild, "timeout",
            f"{user.mention} がタイムアウトされました\n期間: {minutes}分\n理由: {reason or 'なし'}\n実行者: {ctx.user.mention}",
            0xF0B132, user)

    @discord.slash_command(description="ユーザーに警告を送ります")
    @discord.default_permissions(moderate_members=True)
    async def warn(self, ctx: discord.ApplicationContext,
                   user: discord.Option(discord.Member, "対象ユーザー"),
                   reason: discord.Option(str, "理由", required=False)):
        guild_id = str(ctx.guild_id)
        warns    = utils.load(guild_id, "warns.json")
        warns[str(user.id)] = warns.get(str(user.id), 0) + 1
        utils.save(guild_id, "warns.json", warns)

        try:
            e = discord.Embed(
                title="警告",
                description=f"**サーバー**: {ctx.guild.name}\n**理由**: {reason or 'なし'}",
                color=0xF0B132,
                timestamp=datetime.now(timezone.utc),
            )
            await user.send(embed=e)
        except discord.Forbidden:
            pass

        count = warns[str(user.id)]
        await ctx.respond(f"{user.mention} に警告を送りました。（累計: {count}回）", ephemeral=True)
        await self._log(ctx.guild, "warn",
            f"{user.mention} に警告\n理由: {reason or 'なし'}\n累計: **{count}回**\n実行者: {ctx.user.mention}",
            0xF0B132, user)

    @discord.slash_command(description="メッセージを一括削除します")
    @discord.default_permissions(manage_messages=True)
    async def purge(self, ctx: discord.ApplicationContext,
                    count: discord.Option(int, "削除する件数（1〜100）")):
        await ctx.defer(ephemeral=True)
        deleted = await ctx.channel.purge(limit=max(1, min(count, 100)))
        await ctx.followup.send(f"{len(deleted)} 件削除しました。", ephemeral=True)


def setup(bot):
    bot.add_cog(Moderation(bot))
