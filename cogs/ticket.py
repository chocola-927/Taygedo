import discord
from discord.ext import commands
from datetime import datetime, timezone
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import utils


# ── ボタン・UI ────────────────────────────────────────────────────────────────

class TicketCloseButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="チケットを閉じる", style=discord.ButtonStyle.danger,
                       custom_id="ticket:close")
    async def close(self, button, interaction: discord.Interaction):
        cfg = utils.get_config(str(interaction.guild_id))
        admin_role_id = cfg.get("admin_role")

        # 管理者ロールチェック
        if admin_role_id:
            role = interaction.guild.get_role(int(admin_role_id))
            if role and role not in interaction.user.roles:
                return await interaction.response.send_message(
                    "管理者のみ操作できます。", ephemeral=True)

        await interaction.response.send_message("チケットを閉じますか？",
            view=TicketCloseConfirm(), ephemeral=True)


class TicketCloseConfirm(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=30)

    @discord.ui.button(label="閉じる", style=discord.ButtonStyle.danger,
                       custom_id="ticket:close_confirm")
    async def confirm(self, button, interaction: discord.Interaction):
        await interaction.response.defer()
        guild_id = str(interaction.guild_id)
        ch_id    = str(interaction.channel_id)

        tickets = utils.load(guild_id, "tickets.json")
        entry   = tickets.get(ch_id)

        # ログ送信
        cfg = utils.get_config(guild_id)
        if cfg.get("logs", {}).get("ticket") and cfg.get("log_channel"):
            log_ch = interaction.guild.get_channel(int(cfg["log_channel"]))
            if log_ch and entry:
                embed = _log_embed(
                    f"チケット削除",
                    f"<#{ch_id}> が削除されました\n作成者: <@{entry['user_id']}>",
                    0xE8383D, interaction.guild
                )
                await log_ch.send(embed=embed)

        # JSON削除 → チャンネル削除
        if ch_id in tickets:
            del tickets[ch_id]
            utils.save(guild_id, "tickets.json", tickets)

        await interaction.channel.delete()

    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.secondary,
                       custom_id="ticket:close_cancel")
    async def cancel(self, button, interaction: discord.Interaction):
        await interaction.response.defer()
        await interaction.delete_original_response()


class TicketOpenButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="チケットを開く", style=discord.ButtonStyle.primary,
                       custom_id="ticket:open")
    async def open(self, button, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        tickets  = utils.load(guild_id, "tickets.json")

        # 既存チケットチェック
        for ch_id, entry in tickets.items():
            if entry.get("user_id") == str(interaction.user.id):
                return await interaction.response.send_message(
                    f"すでにチケットがあります: <#{ch_id}>", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        cfg      = utils.get_config(guild_id)
        panels   = utils.load(guild_id, "panels.json")
        category_id = panels.get("ticket", {}).get("category_id")
        category    = interaction.guild.get_channel(int(category_id)) if category_id else None

        admin_role_id = cfg.get("admin_role")
        admin_role    = interaction.guild.get_role(int(admin_role_id)) if admin_role_id else None

        # チャンネル権限
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user:               discord.PermissionOverwrite(view_channel=True, send_messages=True),
        }
        if admin_role:
            overwrites[admin_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        ch = await interaction.guild.create_text_channel(
            name=f"ticket-{interaction.user.name}",
            category=category,
            overwrites=overwrites,
        )

        # JSON保存
        tickets[str(ch.id)] = {
            "user_id":    str(interaction.user.id),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        utils.save(guild_id, "tickets.json", tickets)

        # 初期メッセージ
        mentions = interaction.user.mention
        if admin_role:
            mentions += f" {admin_role.mention}"

        embed = discord.Embed(
            description="サポートをお待ちください。\n準備ができたら担当者が対応します。",
            color=0x5865F2,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(name=interaction.user.name,
                         icon_url=interaction.user.display_avatar.url)
        embed.set_footer(text=interaction.guild.name)

        await ch.send(mentions, embed=embed, view=TicketCloseButton())

        # ログ
        if cfg.get("logs", {}).get("ticket") and cfg.get("log_channel"):
            log_ch = interaction.guild.get_channel(int(cfg["log_channel"]))
            if log_ch:
                await log_ch.send(embed=_log_embed(
                    "チケット作成",
                    f"{interaction.user.mention} がチケットを作成しました: {ch.mention}",
                    0x5865F2, interaction.guild,
                ))

        await interaction.followup.send(f"チケットを作成しました: {ch.mention}", ephemeral=True)


# ── ヘルパー ──────────────────────────────────────────────────────────────────

def _log_embed(title, description, color, guild):
    embed = discord.Embed(description=description, color=color,
                          timestamp=datetime.now(timezone.utc))
    embed.set_footer(text=guild.name)
    return embed


# ── Cog ──────────────────────────────────────────────────────────────────────

class Ticket(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        bot.add_view(TicketOpenButton())
        bot.add_view(TicketCloseButton())

    # Persistent View 復元（panel.py の /ticket_panel から呼ばれる場合もある）
    async def restore_panels(self, guild_id: str):
        panels = utils.load(guild_id, "panels.json")
        data   = panels.get("ticket")
        if not data:
            return
        guild = self.bot.get_guild(int(guild_id))
        if not guild:
            return
        ch = guild.get_channel(int(data["channel_id"]))
        if not ch:
            return
        try:
            await ch.fetch_message(int(data["message_id"]))
        except discord.NotFound:
            # メッセージが消えていたら記録を削除
            del panels["ticket"]
            utils.save(guild_id, "panels.json", panels)


def setup(bot):
    bot.add_cog(Ticket(bot))
