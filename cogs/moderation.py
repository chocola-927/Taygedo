import discord
from discord.ext import commands
from datetime import datetime, timezone, timedelta
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import utils


def _log_embed(description, color, guild, user=None):
    e = discord.Embed(description=description, color=color,
                      timestamp=datetime.now(timezone.utc))
    e.set_footer(text=guild.name)
    if user:
        e.set_author(name=user.name, icon_url=user.display_avatar.url)
        e.set_thumbnail(url=user.display_avatar.url)
    return e


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _send_log(self, guild, key, embed):
        cfg   = utils.get_config(str(guild.id))
        if not cfg.get("logs", {}).get(key, True):
            return
        ch_id = cfg.get("log_channel")
        if not ch_id:
            return
        ch = guild.get_channel(int(ch_id))
        if ch:
            await ch.send(embed=embed)

    # ── BAN ───────────────────────────────────────────────────────────────────

    @discord.slash_command(description="ユーザーをBANします")
    @discord.default_permissions(ban_members=True)
    async def ban(self, ctx: discord.ApplicationContext,
                  user: discord.Option(discord.Member, "対象ユーザー"),
                  reason: discord.Option(str, "理由", required=False)):
        try:
            await user.ban(reason=reason)
        except discord.Forbidden:
            return await ctx.respond(
                "BANできませんでした。Botのロールが対象ユーザーより上位か確認してください。",
                ephemeral=True)
        await ctx.respond(f"{user.mention} をBANしました。", ephemeral=True)
        await self._send_log(ctx.guild, "ban", _log_embed(
            f"{user.mention} がBANされました\n"
            f"理由: {reason or 'なし'}\n"
            f"実行者: {ctx.user.mention}",
            0xE8383D, ctx.guild, user))

    # ── Kick ──────────────────────────────────────────────────────────────────

    @discord.slash_command(description="ユーザーをKickします")
    @discord.default_permissions(kick_members=True)
    async def kick(self, ctx: discord.ApplicationContext,
                   user: discord.Option(discord.Member, "対象ユーザー"),
                   reason: discord.Option(str, "理由", required=False)):
        if not hasattr(self.bot, "_kicked_users"):
            self.bot._kicked_users = set()
        self.bot._kicked_users.add(user.id)

        try:
            await user.kick(reason=reason)
        except discord.Forbidden:
            self.bot._kicked_users.discard(user.id)
            return await ctx.respond(
                "Kickできませんでした。Botのロールが対象ユーザーより上位か確認してください。",
                ephemeral=True)
        await ctx.respond(f"{user.mention} をKickしました。", ephemeral=True)
        await self._send_log(ctx.guild, "kick", _log_embed(
            f"{user.mention} がKickされました\n"
            f"理由: {reason or 'なし'}\n"
            f"実行者: {ctx.user.mention}",
            0xE8383D, ctx.guild, user))

    # ── タイムアウト ──────────────────────────────────────────────────────────

    @discord.slash_command(description="ユーザーをタイムアウトします")
    @discord.default_permissions(moderate_members=True)
    async def timeout(self, ctx: discord.ApplicationContext,
                      user: discord.Option(discord.Member, "対象ユーザー"),
                      minutes: discord.Option(int, "分数"),
                      reason: discord.Option(str, "理由", required=False)):
        until = discord.utils.utcnow() + timedelta(minutes=minutes)
        try:
            await user.timeout_for(timedelta(minutes=minutes), reason=reason)
        except discord.Forbidden:
            return await ctx.respond(
                "タイムアウトできませんでした。Botのロールが対象ユーザーより上位か確認してください。",
                ephemeral=True)
        await ctx.respond(f"{user.mention} を {minutes} 分タイムアウトしました。", ephemeral=True)
        await self._send_log(ctx.guild, "timeout", _log_embed(
            f"{user.mention} がタイムアウトされました\n"
            f"期間: {minutes}分（解除: {discord.utils.format_dt(until, 'R')}）\n"
            f"理由: {reason or 'なし'}\n"
            f"実行者: {ctx.user.mention}",
            0xF0B132, ctx.guild, user))

    # ── 警告 ──────────────────────────────────────────────────────────────────

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
                title="⚠️ 警告",
                description=f"**サーバー**: {ctx.guild.name}\n**理由**: {reason or 'なし'}",
                color=0xF0B132,
                timestamp=datetime.now(timezone.utc),
            )
            await user.send(embed=e)
        except discord.Forbidden:
            pass

        count = warns[str(user.id)]
        await ctx.respond(f"{user.mention} に警告を送りました。（累計: {count}回）", ephemeral=True)
        await self._send_log(ctx.guild, "warn", _log_embed(
            f"{user.mention} に警告\n"
            f"理由: {reason or 'なし'}\n"
            f"累計: **{count}回**\n"
            f"実行者: {ctx.user.mention}",
            0xF0B132, ctx.guild, user))

    # ── Purge ─────────────────────────────────────────────────────────────────

    @discord.slash_command(description="メッセージを一括削除します")
    @discord.default_permissions(manage_messages=True)
    async def purge(self, ctx: discord.ApplicationContext,
                    count: discord.Option(int, "削除する件数（1〜100）")):
        await ctx.defer(ephemeral=True)
        deleted = await ctx.channel.purge(limit=max(1, min(count, 100)))
        await ctx.followup.send(f"{len(deleted)} 件削除しました。", ephemeral=True)


def setup(bot):
    bot.add_cog(Moderation(bot))
