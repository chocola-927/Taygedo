import discord
from discord.ext import commands
from datetime import datetime, timezone
import hashlib, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import utils


def _anon_id(user_id: str, guild_id: str) -> str:
    return hashlib.sha256((user_id + guild_id).encode()).hexdigest()[:8]

def _embed(title, description, guild):
    e = discord.Embed(title=title, description=description, color=0x5865F2,
                      timestamp=datetime.now(timezone.utc))
    e.set_footer(text=guild.name)
    return e


class AnonTicketModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="匿名チケット")
        self.add_item(discord.ui.InputText(
            label="内容", style=discord.InputTextStyle.long,
            placeholder="相談内容を入力してください", max_length=1000,
        ))

    async def callback(self, interaction: discord.Interaction):
        content  = self.children[0].value
        guild_id = str(interaction.guild_id)
        user_id  = str(interaction.user.id)
        anon_id  = _anon_id(user_id, guild_id)
        tickets  = utils.load(guild_id, "tickets.json")

        # 既存チケットへの追加メッセージ
        for ch_id, entry in tickets.items():
            if entry.get("type") == "anon" and entry.get("anon_id") == anon_id:
                ch = interaction.guild.get_channel(int(ch_id))
                if ch:
                    await ch.send(embed=_embed(f"[{anon_id}] 追加メッセージ", content, interaction.guild))
                await interaction.response.send_message("メッセージを送信しました。", ephemeral=True)
                return

        await interaction.response.defer(ephemeral=True)

        cfg           = utils.get_config(guild_id)
        panels        = utils.load(guild_id, "panels.json")
        category_id   = panels.get("anon_ticket", {}).get("category_id")
        category      = interaction.guild.get_channel(int(category_id)) if category_id else None
        admin_role_id = cfg.get("admin_role")
        admin_role    = interaction.guild.get_role(int(admin_role_id)) if admin_role_id else None

        overwrites = {interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False)}
        if admin_role:
            overwrites[admin_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        ch = await interaction.guild.create_text_channel(
            name=f"anon-{anon_id}", category=category, overwrites=overwrites)

        tickets[str(ch.id)] = {
            "type": "anon", "anon_id": anon_id, "user_id": user_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        utils.save(guild_id, "tickets.json", tickets)

        mention = admin_role.mention if admin_role else ""
        await ch.send(mention, embed=_embed(f"匿名チケット [{anon_id}]", content, interaction.guild),
                      view=AnonTicketCloseButton())

        if cfg.get("logs", {}).get("ticket") and cfg.get("log_channel"):
            log_ch = interaction.guild.get_channel(int(cfg["log_channel"]))
            if log_ch:
                await log_ch.send(embed=_embed(
                    "匿名チケット作成",
                    f"匿名チケットが作成されました: {ch.mention}\nID: `{anon_id}`",
                    interaction.guild,
                ))

        await interaction.followup.send(
            f"匿名チケットを作成しました。管理者が返信します。\nID: `{anon_id}`", ephemeral=True)


class AnonReplyModal(discord.ui.Modal):
    def __init__(self, anon_id: str, user_id: int):
        super().__init__(title="匿名チケットへの返信")
        self.anon_id = anon_id
        self.user_id = user_id
        self.add_item(discord.ui.InputText(
            label="返信内容", style=discord.InputTextStyle.long, max_length=1000))

    async def callback(self, interaction: discord.Interaction):
        try:
            user  = await interaction.client.fetch_user(self.user_id)
            embed = discord.Embed(
                title=f"匿名チケット [{self.anon_id}] への返信",
                description=self.children[0].value,
                color=0x5865F2,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_footer(text=interaction.guild.name)
            await user.send(embed=embed)
            await interaction.response.send_message("返信を送信しました。", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(
                "DMを送信できません。", ephemeral=True)


class AnonTicketOpenButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="匿名チケットを開く", style=discord.ButtonStyle.secondary,
                       custom_id="anon_ticket:open")
    async def open(self, button, interaction: discord.Interaction):
        await interaction.response.send_modal(AnonTicketModal())


class AnonTicketCloseButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="返信する", style=discord.ButtonStyle.primary,
                       custom_id="anon_ticket:reply")
    async def reply(self, button, interaction: discord.Interaction):
        tickets = utils.load(str(interaction.guild_id), "tickets.json")
        entry   = tickets.get(str(interaction.channel_id))
        if not entry:
            return await interaction.response.send_message("チケット情報が見つかりません。", ephemeral=True)
        await interaction.response.send_modal(
            AnonReplyModal(entry["anon_id"], int(entry["user_id"])))

    @discord.ui.button(label="閉じる", style=discord.ButtonStyle.danger,
                       custom_id="anon_ticket:close")
    async def close(self, button, interaction: discord.Interaction):
        guild_id      = str(interaction.guild_id)
        cfg           = utils.get_config(guild_id)
        admin_role_id = cfg.get("admin_role")
        if admin_role_id:
            role = interaction.guild.get_role(int(admin_role_id))
            if role and role not in interaction.user.roles:
                return await interaction.response.send_message("管理者のみ操作できます。", ephemeral=True)

        ch_id   = str(interaction.channel_id)
        tickets = utils.load(guild_id, "tickets.json")
        entry   = tickets.get(ch_id, {})

        if cfg.get("logs", {}).get("ticket") and cfg.get("log_channel"):
            log_ch = interaction.guild.get_channel(int(cfg["log_channel"]))
            if log_ch:
                await log_ch.send(embed=_embed(
                    "匿名チケット削除",
                    f"削除: <#{ch_id}>\nID: `{entry.get('anon_id', '?')}`",
                    interaction.guild,
                ))

        if ch_id in tickets:
            del tickets[ch_id]
            utils.save(guild_id, "tickets.json", tickets)

        await interaction.response.defer()
        await interaction.channel.delete()


class AnonTicket(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        bot.add_view(AnonTicketOpenButton())
        bot.add_view(AnonTicketCloseButton())

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """ユーザーDM → チケットチャンネルへ中継"""
        if message.author.bot or message.guild:
            return
        user_id = str(message.author.id)
        for guild in self.bot.guilds:
            guild_id = str(guild.id)
            tickets  = utils.load(guild_id, "tickets.json")
            for ch_id, entry in tickets.items():
                if entry.get("type") == "anon" and entry.get("user_id") == user_id:
                    ch = guild.get_channel(int(ch_id))
                    if ch:
                        await ch.send(embed=_embed(
                            f"[{entry['anon_id']}] ユーザーからのメッセージ",
                            message.content, guild,
                        ))
                    return


def setup(bot):
    bot.add_cog(AnonTicket(bot))
