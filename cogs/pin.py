import discord
from discord.ext import commands
from datetime import datetime, timezone
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import utils


# ── Webhook で送信 ────────────────────────────────────────────────────────────

async def _send_pinned(channel: discord.TextChannel,
                       source_msg: discord.Message) -> tuple[discord.Webhook, int]:
    """Webhookを作成して元メッセージを送信し、(webhook, message_id) を返す"""
    wh = await channel.create_webhook(name="Taygedo Pin")

    content = source_msg.content or None
    files   = []
    for att in source_msg.attachments:
        try:
            files.append(await att.to_file())
        except Exception:
            pass

    sent = await wh.send(
        content=content,
        username=source_msg.author.display_name,
        avatar_url=source_msg.author.display_avatar.url,
        files=files,
        wait=True,
    )
    return wh, sent.id


# ── 固定解除ヘルパー ──────────────────────────────────────────────────────────

async def _unpin(channel: discord.TextChannel, entry: dict, guild_id: str, ch_id: str):
    """Webhookとメッセージを削除し、pins.jsonから削除する"""
    # Webhookごと削除（メッセージも一緒に消える）
    wh_id = entry.get("webhook_id")
    if wh_id:
        try:
            webhooks = await channel.webhooks()
            for wh in webhooks:
                if str(wh.id) == wh_id:
                    await wh.delete()
                    break
        except (discord.NotFound, discord.Forbidden):
            pass

    pins = utils.load(guild_id, "pins.json")
    if ch_id in pins:
        del pins[ch_id]
        utils.save(guild_id, "pins.json", pins)


# ── 上書き確認View ────────────────────────────────────────────────────────────

class PinOverwriteView(discord.ui.View):
    def __init__(self, channel: discord.TextChannel, target_message: discord.Message,
                 guild_id: str, ch_id: str, existing_entry: dict):
        super().__init__(timeout=30)
        self.channel        = channel
        self.target         = target_message
        self.guild_id       = guild_id
        self.ch_id          = ch_id
        self.existing_entry = existing_entry

    @discord.ui.button(label="解除して固定", style=discord.ButtonStyle.danger)
    async def confirm(self, button, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        # 既存の固定を解除
        await _unpin(self.channel, self.existing_entry, self.guild_id, self.ch_id)

        # 新しい固定を作成
        try:
            wh, msg_id = await _send_pinned(self.channel, self.target)
        except discord.Forbidden:
            return await interaction.followup.send(
                "Webhookの作成権限がありません。", ephemeral=True)

        pins = utils.load(self.guild_id, "pins.json")
        pins[self.ch_id] = {
            "source_message_id":  str(self.target.id),
            "current_message_id": str(msg_id),
            "webhook_id":         str(wh.id),
        }
        utils.save(self.guild_id, "pins.json", pins)
        await interaction.followup.send("固定しました。", ephemeral=True)

    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.secondary)
    async def cancel(self, button, interaction: discord.Interaction):
        await interaction.response.edit_message(content="キャンセルしました。", view=None)


# ── セレクト ──────────────────────────────────────────────────────────────────

class PinSelect(discord.ui.View):
    def __init__(self, target_message: discord.Message):
        super().__init__(timeout=60)
        self.target = target_message

    @discord.ui.select(
        placeholder="操作を選択",
        options=[
            discord.SelectOption(label="固定", value="pin"),
            discord.SelectOption(label="固定解除", value="unpin"),
        ],
        custom_id="pin:select",
    )
    async def select(self, select: discord.ui.Select, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        ch_id    = str(self.target.channel.id)
        pins     = utils.load(guild_id, "pins.json")

        if select.values[0] == "pin":
            # すでに固定中なら警告
            if ch_id in pins:
                existing = pins[ch_id]
                view = PinOverwriteView(
                    self.target.channel, self.target,
                    guild_id, ch_id, existing,
                )
                return await interaction.response.edit_message(
                    content=(
                        "⚠️ このチャンネルにはすでに固定されたメッセージがあります。\n"
                        "先に固定されているメッセージを解除して続行しますか？"
                    ),
                    view=view,
                )

            # 新規固定
            try:
                wh, msg_id = await _send_pinned(self.target.channel, self.target)
            except discord.Forbidden:
                return await interaction.response.edit_message(
                    content="Webhookの作成権限がありません。", view=None)

            pins[ch_id] = {
                "source_message_id":  str(self.target.id),
                "current_message_id": str(msg_id),
                "webhook_id":         str(wh.id),
            }
            utils.save(guild_id, "pins.json", pins)
            await interaction.response.edit_message(content="固定しました。", view=None)

        else:  # unpin
            if ch_id not in pins:
                return await interaction.response.edit_message(
                    content="固定されたメッセージがありません。", view=None)

            await _unpin(self.target.channel, pins[ch_id], guild_id, ch_id)
            await interaction.response.edit_message(content="固定を解除しました。", view=None)


# ── Cog ──────────────────────────────────────────────────────────────────────

class Pin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.message_command(name="メッセージを固定")
    async def pin_menu(self, ctx: discord.ApplicationContext, message: discord.Message):
        view = PinSelect(message)
        await ctx.respond("操作を選択してください。", view=view, ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """新着メッセージが来たら固定メッセージを一番下に送り直す"""
        if not message.guild or message.author == self.bot.user:
            return
        if message.webhook_id:
            return

        guild_id = str(message.guild.id)
        ch_id    = str(message.channel.id)
        pins     = utils.load(guild_id, "pins.json")

        if ch_id not in pins:
            return

        entry = pins[ch_id]

        # 元メッセージを取得
        try:
            source_msg = await message.channel.fetch_message(
                int(entry["source_message_id"]))
        except discord.NotFound:
            # 元メッセージが消えていたら固定解除
            await _unpin(message.channel, entry, guild_id, ch_id)
            return

        # 古いWebhookを削除
        wh_id = entry.get("webhook_id")
        if wh_id:
            try:
                webhooks = await message.channel.webhooks()
                for wh in webhooks:
                    if str(wh.id) == wh_id:
                        await wh.delete()
                        break
            except (discord.NotFound, discord.Forbidden):
                pass

        # 送り直す
        try:
            wh, msg_id = await _send_pinned(message.channel, source_msg)
        except Exception:
            return

        pins[ch_id]["current_message_id"] = str(msg_id)
        pins[ch_id]["webhook_id"]         = str(wh.id)
        utils.save(guild_id, "pins.json", pins)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        """元メッセージが消されたら固定解除"""
        if not message.guild:
            return

        guild_id = str(message.guild.id)
        ch_id    = str(message.channel.id)
        pins     = utils.load(guild_id, "pins.json")

        if ch_id not in pins:
            return

        if pins[ch_id].get("source_message_id") == str(message.id):
            await _unpin(message.channel, pins[ch_id], guild_id, ch_id)


def setup(bot):
    bot.add_cog(Pin(bot))
