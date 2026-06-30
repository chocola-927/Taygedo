import asyncio
import discord
from discord.ext import commands
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import utils


WEBHOOK_NAME = "Taygedo Pin"

# チャンネルごとのロック（同時メッセージによるrace conditionを防ぐ）
_channel_locks: dict[int, asyncio.Lock] = {}


def _get_lock(channel_id: int) -> asyncio.Lock:
    lock = _channel_locks.get(channel_id)
    if lock is None:
        lock = asyncio.Lock()
        _channel_locks[channel_id] = lock
    return lock


# ── Webhook ヘルパー ──────────────────────────────────────────────────────────

async def _find_webhook(channel: discord.TextChannel, wh_id: str) -> discord.Webhook | None:
    """チャンネルのWebhook一覧からIDで探す（from_urlのsession問題を回避）"""
    try:
        webhooks = await channel.webhooks()
        for wh in webhooks:
            if str(wh.id) == wh_id:
                return wh
    except (discord.NotFound, discord.Forbidden):
        pass
    return None


async def _get_or_create_webhook(channel: discord.TextChannel, wh_id: str | None) -> discord.Webhook:
    """既存のWebhookがあれば使い回し、なければ作成する（毎回delete/createしない）"""
    if wh_id:
        wh = await _find_webhook(channel, wh_id)
        if wh:
            return wh
    return await channel.create_webhook(name=WEBHOOK_NAME)


async def _send_from_message(channel: discord.TextChannel, source: discord.Message,
                             webhook: discord.Webhook) -> int:
    """既存のメッセージ（自分のWebhookメッセージ含む）の内容をそのまま再送信する"""
    content = source.content or None
    files = []
    for att in source.attachments:
        try:
            files.append(await att.to_file())
        except Exception as e:
            print(f"[pin] attachment fetch failed ({att.filename}): {e}")

    sent = await webhook.send(
        content=content,
        username=source.author.display_name,
        avatar_url=source.author.display_avatar.url,
        files=files,
        embeds=source.embeds,
        allowed_mentions=discord.AllowedMentions.none(),
        wait=True,
    )
    return sent.id


async def _delete_pinned_message(channel: discord.TextChannel, entry: dict):
    """固定メッセージ自体だけを削除する（Webhookは削除しない）"""
    msg_id = entry.get("current_message_id")
    if not msg_id:
        return
    try:
        msg = await channel.fetch_message(int(msg_id))
        await msg.delete()
    except (discord.NotFound, discord.Forbidden) as e:
        print(f"[pin] pinned message delete skipped: {e}")


async def _delete_webhook_safe(channel: discord.TextChannel, entry: dict):
    """固定解除時など、Webhookごと消したい場合に使う"""
    wh_id = entry.get("webhook_id")
    if not wh_id:
        return
    wh = await _find_webhook(channel, wh_id)
    if wh:
        try:
            await wh.delete()
        except (discord.NotFound, discord.Forbidden) as e:
            print(f"[pin] webhook delete skipped: {e}")


async def _unpin(channel: discord.TextChannel, entry: dict, guild_id: str, ch_id: str):
    await _delete_webhook_safe(channel, entry)
    pins = utils.load(guild_id, "pins.json")
    if ch_id in pins:
        del pins[ch_id]
        utils.save(guild_id, "pins.json", pins)


async def _resend_pin(channel: discord.TextChannel, guild_id: str, ch_id: str,
                       entry: dict, source: discord.Message) -> bool:
    """Webhookを使い回して、固定メッセージを一番下に送り直す。
    失敗した場合はpins.jsonを書き換えずFalseを返す（不整合を避ける）。"""
    try:
        wh = await _get_or_create_webhook(channel, entry.get("webhook_id"))
    except discord.Forbidden:
        print("[pin] resend failed: missing webhook permission")
        return False
    except Exception as e:
        print(f"[pin] resend failed (webhook get/create): {e}")
        return False

    try:
        new_msg_id = await _send_from_message(channel, source, wh)
    except Exception as e:
        print(f"[pin] resend failed (send): {e}")
        return False

    # 送信が成功してから古いメッセージを消す（消す→送るの順だと送信失敗時に固定が消えたままになる）
    await _delete_pinned_message(channel, entry)

    pins = utils.load(guild_id, "pins.json")
    pins[ch_id] = {
        "source_message_id":  entry.get("source_message_id", str(source.id)),
        "current_message_id": str(new_msg_id),
        "webhook_id":          str(wh.id),
    }
    utils.save(guild_id, "pins.json", pins)
    return True


# ── 上書き確認View ────────────────────────────────────────────────────────────

class PinOverwriteView(discord.ui.View):
    def __init__(self, channel, target_message, guild_id, ch_id, existing_entry):
        super().__init__(timeout=30)
        self.channel = channel
        self.target = target_message
        self.guild_id = guild_id
        self.ch_id = ch_id
        self.existing_entry = existing_entry

    @discord.ui.button(label="解除して固定", style=discord.ButtonStyle.danger)
    async def confirm(self, button, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        async with _get_lock(self.channel.id):
            await _unpin(self.channel, self.existing_entry, self.guild_id, self.ch_id)

            try:
                wh = await _get_or_create_webhook(self.channel, None)
                msg_id = await _send_from_message(self.channel, self.target, wh)
            except discord.Forbidden:
                return await interaction.followup.send("Webhookの作成権限がありません。", ephemeral=True)
            except Exception as e:
                print(f"[pin] overwrite send failed: {e}")
                return await interaction.followup.send("固定メッセージの送信に失敗しました。", ephemeral=True)

            pins = utils.load(self.guild_id, "pins.json")
            pins[self.ch_id] = {
                "source_message_id":  str(self.target.id),
                "current_message_id": str(msg_id),
                "webhook_id":          str(wh.id),
            }
            utils.save(self.guild_id, "pins.json", pins)
        await interaction.followup.send("固定しました。", ephemeral=True)

    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.secondary)
    async def cancel(self, button, interaction: discord.Interaction):
        await interaction.response.edit_message(content="キャンセルしました。", view=None)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        try:
            if self.message:
                await self.message.edit(view=self)
        except discord.HTTPException:
            pass


# ── セレクト ──────────────────────────────────────────────────────────────────

class PinSelect(discord.ui.View):
    def __init__(self, target_message):
        super().__init__(timeout=60)
        self.target = target_message
        self.message = None

    @discord.ui.select(
        placeholder="操作を選択",
        options=[
            discord.SelectOption(label="固定", value="pin"),
            discord.SelectOption(label="固定解除", value="unpin"),
        ],
        custom_id="pin:select",
    )
    async def select(self, select, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        ch_id = str(self.target.channel.id)

        async with _get_lock(self.target.channel.id):
            pins = utils.load(guild_id, "pins.json")

            if select.values[0] == "pin":
                if ch_id in pins:
                    existing = pins[ch_id]
                    view = PinOverwriteView(self.target.channel, self.target, guild_id, ch_id, existing)
                    msg = await interaction.response.edit_message(
                        content=(
                            "⚠️ このチャンネルにはすでに固定されたメッセージがあります。\n"
                            "先に固定されているメッセージを解除して続行しますか？"
                        ),
                        view=view,
                    )
                    view.message = interaction.message
                    return

                try:
                    wh = await _get_or_create_webhook(self.target.channel, None)
                    msg_id = await _send_from_message(self.target.channel, self.target, wh)
                except discord.Forbidden:
                    return await interaction.response.edit_message(content="Webhookの作成権限がありません。", view=None)
                except Exception as e:
                    print(f"[pin] new pin send failed: {e}")
                    return await interaction.response.edit_message(content="固定メッセージの送信に失敗しました。", view=None)

                pins[ch_id] = {
                    "source_message_id":  str(self.target.id),
                    "current_message_id": str(msg_id),
                    "webhook_id":          str(wh.id),
                }
                utils.save(guild_id, "pins.json", pins)
                await interaction.response.edit_message(content="固定しました。", view=None)
            else:
                if ch_id not in pins:
                    return await interaction.response.edit_message(content="固定されたメッセージがありません。", view=None)
                await _unpin(self.target.channel, pins[ch_id], guild_id, ch_id)
                await interaction.response.edit_message(content="固定を解除しました。", view=None)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        try:
            if self.message:
                await self.message.edit(view=self)
        except discord.HTTPException:
            pass


# ── Cog ──────────────────────────────────────────────────────────────────────

class Pin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.message_command(name="メッセージを固定")
    async def pin_menu(self, ctx: discord.ApplicationContext, message: discord.Message):
        view = PinSelect(message)
        resp = await ctx.respond("操作を選択してください。", view=view, ephemeral=True)
        view.message = await resp.original_response() if hasattr(resp, "original_response") else None

    @discord.slash_command(description="現在固定中のメッセージ一覧を表示します")
    async def pin_list(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True)

        guild_id = str(ctx.guild_id)
        pins     = utils.load(guild_id, "pins.json")

        if not pins:
            return await ctx.respond("現在固定されているメッセージはありません。", ephemeral=True)

        embed = discord.Embed(
            title="📌 固定メッセージ一覧",
            color=0x5865F2,
        )

        for ch_id, entry in pins.items():
            ch = ctx.guild.get_channel(int(ch_id))
            ch_name = f"#{ch.name}" if ch else f"不明なチャンネル ({ch_id})"

            content = "*(取得できませんでした)*"
            if ch:
                try:
                    msg = await ch.fetch_message(int(entry["current_message_id"]))
                    content = msg.content or "*(添付ファイルのみ)*"
                    if len(content) > 200:
                        content = content[:200] + "..."
                except discord.NotFound:
                    content = "*(固定メッセージが見つかりません)*"

            embed.add_field(name=ch_name, value=content, inline=False)

        await ctx.respond(embed=embed, ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """新着メッセージが来たら、固定済みのWebhookメッセージを取得して一番下に送り直す"""
        if not message.guild or message.author == self.bot.user:
            return

        guild_id = str(message.guild.id)
        ch_id = str(message.channel.id)

        async with _get_lock(message.channel.id):
            pins = utils.load(guild_id, "pins.json")

            if ch_id not in pins:
                return

            entry = pins[ch_id]

            # 自分の固定用Webhookからのメッセージだけは無視する（他Botのwebhookは無視しない）
            if message.webhook_id and str(message.webhook_id) == entry.get("webhook_id"):
                return

            # 現在固定中のWebhookメッセージ自体をfetch
            try:
                current_msg = await message.channel.fetch_message(int(entry["current_message_id"]))
            except discord.NotFound:
                # 固定メッセージが手動で消されていたら固定解除
                await _unpin(message.channel, entry, guild_id, ch_id)
                return

            await _resend_pin(message.channel, guild_id, ch_id, entry, current_msg)


def setup(bot):
    bot.add_cog(Pin(bot))
