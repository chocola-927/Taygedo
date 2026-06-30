import discord
from discord.ext import commands
from datetime import datetime, timezone
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import utils


# ── Webhook ヘルパー ──────────────────────────────────────────────────────────
async def _get_or_create_webhook(channel: discord.TextChannel, entry: dict | None) -> discord.Webhook:
    if entry and entry.get("webhook_id") and entry.get("webhook_token"):
        return discord.Webhook.from_url(
            f"https://discord.com/api/webhooks/{entry['webhook_id']}/{entry['webhook_token']}",
        )
    return await channel.create_webhook(name="Taygedo Pin")


async def _send_pinned(channel: discord.TextChannel, source_msg: discord.Message,
                        webhook: discord.Webhook) -> int:
    content = source_msg.content or None
    files = []
    for att in source_msg.attachments:
        if not (att.content_type or "").startswith("image/"):
            continue
        try:
            files.append(await att.to_file())
        except Exception as e:
            print(f"[pin] attachment fetch failed ({att.filename}): {e}")

    sent = await webhook.send(
        content=content,
        username=source_msg.author.display_name,
        avatar_url=source_msg.author.display_avatar.url,
        files=files,
        wait=True,
    )
    return sent.id


async def _delete_webhook_safe(entry: dict):
    wh_id = entry.get("webhook_id")
    wh_token = entry.get("webhook_token")
    if not (wh_id and wh_token):
        return
    try:
        wh = discord.Webhook.from_url(
            f"https://discord.com/api/webhooks/{wh_id}/{wh_token}",
        )
        await wh.delete()
    except (discord.NotFound, discord.Forbidden) as e:
        print(f"[pin] webhook delete skipped: {e}")


async def _unpin(entry: dict, guild_id: str, ch_id: str):
    await _delete_webhook_safe(entry)
    pins = utils.load(guild_id, "pins.json")
    if ch_id in pins:
        del pins[ch_id]
        utils.save(guild_id, "pins.json", pins)


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
        await _unpin(self.existing_entry, self.guild_id, self.ch_id)
        try:
            wh = await _get_or_create_webhook(self.channel, None)
            msg_id = await _send_pinned(self.channel, self.target, wh)
        except discord.Forbidden:
            return await interaction.followup.send("Webhookの作成権限がありません。", ephemeral=True)
        except Exception as e:
            print(f"[pin] overwrite send failed: {e}")
            return await interaction.followup.send("固定メッセージの送信に失敗しました。", ephemeral=True)

        pins = utils.load(self.guild_id, "pins.json")
        pins[self.ch_id] = {
            "source_message_id": str(self.target.id),
            "current_message_id": str(msg_id),
            "webhook_id": str(wh.id),
            "webhook_token": wh.token,
        }
        utils.save(self.guild_id, "pins.json", pins)
        await interaction.followup.send("固定しました。", ephemeral=True)

    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.secondary)
    async def cancel(self, button, interaction: discord.Interaction):
        await interaction.response.edit_message(content="キャンセルしました。", view=None)


# ── セレクト ──────────────────────────────────────────────────────────────────
class PinSelect(discord.ui.View):
    def __init__(self, target_message):
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
    async def select(self, select, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        ch_id = str(self.target.channel.id)
        pins = utils.load(guild_id, "pins.json")

        if select.values[0] == "pin":
            if ch_id in pins:
                existing = pins[ch_id]
                view = PinOverwriteView(self.target.channel, self.target, guild_id, ch_id, existing)
                return await interaction.response.edit_message(
                    content=(
                        "⚠️ このチャンネルにはすでに固定されたメッセージがあります。\n"
                        "先に固定されているメッセージを解除して続行しますか？"
                    ),
                    view=view,
                )
            try:
                wh = await _get_or_create_webhook(self.target.channel, None)
                msg_id = await _send_pinned(self.target.channel, self.target, wh)
            except discord.Forbidden:
                return await interaction.response.edit_message(content="Webhookの作成権限がありません。", view=None)
            except Exception as e:
                print(f"[pin] new pin send failed: {e}")
                return await interaction.response.edit_message(content="固定メッセージの送信に失敗しました。", view=None)

            pins[ch_id] = {
                "source_message_id": str(self.target.id),
                "current_message_id": str(msg_id),
                "webhook_id": str(wh.id),
                "webhook_token": wh.token,
            }
            utils.save(guild_id, "pins.json", pins)
            await interaction.response.edit_message(content="固定しました。", view=None)
        else:
            if ch_id not in pins:
                return await interaction.response.edit_message(content="固定されたメッセージがありません。", view=None)
            await _unpin(pins[ch_id], guild_id, ch_id)
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
        if not message.guild or message.author == self.bot.user:
            return
        if message.webhook_id:
            print(f"[pin] skipping webhook message in #{message.channel}")
            return

        guild_id = str(message.guild.id)
        ch_id = str(message.channel.id)
        pins = utils.load(guild_id, "pins.json")

        print(f"[pin] on_message: ch={ch_id} pinned={ch_id in pins}")

        if ch_id not in pins:
            return

        entry = pins[ch_id]
        print(f"[pin] reposting pin in #{message.channel}")

        try:
            source_msg = await message.channel.fetch_message(int(entry["source_message_id"]))
        except discord.NotFound:
            print(f"[pin] source message gone, unpinning")
            await _unpin(entry, guild_id, ch_id)
            return

        try:
            wh = await _get_or_create_webhook(message.channel, entry)
            new_msg_id = await _send_pinned(message.channel, source_msg, wh)
        except (discord.NotFound, discord.Forbidden) as e:
            print(f"[pin] webhook unusable, recreating: {e}")
            try:
                wh = await message.channel.create_webhook(name="Taygedo Pin")
                new_msg_id = await _send_pinned(message.channel, source_msg, wh)
            except Exception as e2:
                print(f"[pin] webhook recreate failed: {e2}")
                return
        except Exception as e:
            print(f"[pin] resend failed: {e}")
            return

        pins[ch_id]["current_message_id"] = str(new_msg_id)
        pins[ch_id]["webhook_id"] = str(wh.id)
        pins[ch_id]["webhook_token"] = wh.token
        utils.save(guild_id, "pins.json", pins)
        print(f"[pin] done, new msg_id={new_msg_id}")

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not message.guild:
            return
        guild_id = str(message.guild.id)
        ch_id = str(message.channel.id)
        pins = utils.load(guild_id, "pins.json")
        if ch_id not in pins:
            return
        if pins[ch_id].get("source_message_id") == str(message.id):
            await _unpin(pins[ch_id], guild_id, ch_id)


def setup(bot):
    bot.add_cog(Pin(bot))
