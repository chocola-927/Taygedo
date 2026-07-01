import asyncio
import discord
import aiohttp
import json
from discord.ext import commands
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import utils


WEBHOOK_NAME = "Taygedo Pin"
RESEND_DEBOUNCE_SECONDS = 5  # 連投中はこの秒数だけ待ってから1回だけ再送信する

# チャンネルごとのロック（同時メッセージによるrace conditionを防ぐ）
_channel_locks: dict[int, asyncio.Lock] = {}

# チャンネルごとの「再送信予約」タスク（連投対策のデバウンス用）
_resend_tasks: dict[int, asyncio.Task] = {}

# pins.jsonのキャッシュ（guild_id -> pins dict）。毎回ファイルI/Oしないようにする
_PIN_CACHE: dict[str, dict] = {}

# Webhookのキャッシュ（channel_id -> discord.Webhook）。毎回channel.webhooks()を叩かないようにする
_WEBHOOK_CACHE: dict[int, discord.Webhook] = {}


def _get_pins(guild_id: str) -> dict:
    """pins.jsonをキャッシュ付きで取得する"""
    if guild_id not in _PIN_CACHE:
        _PIN_CACHE[guild_id] = utils.load(guild_id, "pins.json")
    return _PIN_CACHE[guild_id]


def _save_pins(guild_id: str, pins: dict):
    """pins.jsonを保存し、キャッシュも更新する"""
    _PIN_CACHE[guild_id] = pins
    utils.save(guild_id, "pins.json", pins)


class PinUnsupportedContentError(Exception):
    """Webhookでは転送できない内容（スタンプのみ等）のメッセージを固定しようとした場合に投げる"""
    pass


def _get_lock(channel_id: int) -> asyncio.Lock:
    lock = _channel_locks.get(channel_id)
    if lock is None:
        lock = asyncio.Lock()
        _channel_locks[channel_id] = lock
    return lock


# ── Webhook ヘルパー ──────────────────────────────────────────────────────────

async def _find_webhook(channel: discord.TextChannel, wh_id: str) -> discord.Webhook | None:
    """チャンネルのWebhook一覧からIDで探す（from_urlのsession問題を回避）。
    キャッシュにあれば一覧取得APIを叩かずに済ませる"""
    cached = _WEBHOOK_CACHE.get(channel.id)
    if cached and str(cached.id) == wh_id:
        return cached

    try:
        webhooks = await channel.webhooks()
        for wh in webhooks:
            if str(wh.id) == wh_id:
                _WEBHOOK_CACHE[channel.id] = wh
                return wh
    except (discord.NotFound, discord.Forbidden) as e:
        print(f"[pin] could not list webhooks in #{channel.name}: {e}")
    return None


async def _get_or_create_webhook(channel: discord.TextChannel, wh_id: str | None) -> discord.Webhook:
    """既存のWebhookがあれば使い回し、なければ作成する（毎回delete/createしない）"""
    if wh_id:
        wh = await _find_webhook(channel, wh_id)
        if wh:
            return wh
    wh = await channel.create_webhook(name=WEBHOOK_NAME)
    _WEBHOOK_CACHE[channel.id] = wh
    return wh


async def _send_from_message(
    channel: discord.TextChannel,
    source: discord.Message,
    webhook: discord.Webhook,
) -> int:
    """Webhook APIを直接叩いて通知なしで送信する"""

    content = source.content or None

    if (
        not content
        and not source.attachments
        and not source.embeds
    ):
        if source.stickers:
            raise PinUnsupportedContentError(
                "スタンプのみのメッセージは固定できません（Webhookはスタンプを転送できません）。"
            )
        raise PinUnsupportedContentError(
            "固定できる内容（テキスト・添付・埋め込み）がありません。"
        )

    flags = getattr(source, "flags", None)
    suppress = bool(flags and getattr(flags, "suppress_embeds", False))

    payload = {
        "content": content,
        "username": source.author.display_name,
        "avatar_url": source.author.display_avatar.url,
        "allowed_mentions": {
            "parse": []
        },
        "flags": 4096,
    }

    if source.embeds:
        payload["embeds"] = [e.to_dict() for e in source.embeds]

    if suppress:
        payload["flags"] |= 4   # SUPPRESS_EMBEDS

    form = aiohttp.FormData()

    form.add_field(
        "payload_json",
        json.dumps(payload),
        content_type="application/json",
    )

    for i, att in enumerate(source.attachments):
        try:
            data = await att.read()

            form.add_field(
                f"files[{i}]",
                data,
                filename=att.filename,
                content_type=att.content_type or "application/octet-stream",
            )

        except Exception as e:
            print(f"[pin] attachment fetch failed ({att.filename}): {e}")

    url = (
        f"https://discord.com/api/v10/webhooks/"
        f"{webhook.id}/{webhook.token}"
        "?wait=true"
    )

    async with aiohttp.ClientSession() as session:
        async with session.post(url, data=form) as resp:

            if resp.status >= 400:
                text = await resp.text()
                raise RuntimeError(
                    f"Webhook API {resp.status}: {text}"
                )

            data = await resp.json()

    return int(data["id"])

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
        print("[pin] webhook delete skipped: entry has no webhook_id")
        return
    wh = await _find_webhook(channel, wh_id)
    if wh is None:
        print(f"[pin] webhook delete skipped: webhook {wh_id} not found in #{channel.name} "
              f"(already deleted manually, or webhooks() permission missing)")
        return
    try:
        await wh.delete()
    except (discord.NotFound, discord.Forbidden) as e:
        print(f"[pin] webhook delete skipped: {e}")
    finally:
        _WEBHOOK_CACHE.pop(channel.id, None)


async def _unpin(channel: discord.TextChannel, entry: dict, guild_id: str, ch_id: str):
    await _delete_webhook_safe(channel, entry)
    pins = _get_pins(guild_id)
    if ch_id in pins:
        del pins[ch_id]
        _save_pins(guild_id, pins)


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
    except PinUnsupportedContentError as e:
        print(f"[pin] resend skipped: {e}")
        return False
    except Exception as e:
        print(f"[pin] resend failed (send): {e}")
        return False

    # 送信が成功してから古いメッセージを消す（消す→送るの順だと送信失敗時に固定が消えたままになる）
    await _delete_pinned_message(channel, entry)

    pins = _get_pins(guild_id)
    pins[ch_id] = {
        "source_message_id":  entry.get("source_message_id", str(source.id)),
        "current_message_id": str(new_msg_id),
        "webhook_id":          str(wh.id),
    }
    _save_pins(guild_id, pins)
    return True


async def _debounced_resend(channel: discord.TextChannel, guild_id: str, ch_id: str):
    """RESEND_DEBOUNCE_SECONDS秒待ってから1回だけ再送信する。
    待っている間に別のメッセージが来てキャンセルされたら何もしない。"""
    try:
        await asyncio.sleep(RESEND_DEBOUNCE_SECONDS)
    except asyncio.CancelledError:
        return

    async with _get_lock(channel.id):
        pins = _get_pins(guild_id)
        entry = pins.get(ch_id)
        if not entry:
            return

        try:
            current_msg = await channel.fetch_message(int(entry["current_message_id"]))
        except discord.NotFound:
            await _unpin(channel, entry, guild_id, ch_id)
            return

        await _resend_pin(channel, guild_id, ch_id, entry, current_msg)

    _resend_tasks.pop(channel.id, None)


def _schedule_resend(channel: discord.TextChannel, guild_id: str, ch_id: str):
    """連投対策: すでに予約済みの再送信があればキャンセルして予約し直す（デバウンス）。"""
    existing = _resend_tasks.get(channel.id)
    if existing and not existing.done():
        existing.cancel()
    _resend_tasks[channel.id] = asyncio.create_task(
        _debounced_resend(channel, guild_id, ch_id)
    )


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
            except PinUnsupportedContentError as e:
                return await interaction.followup.send(str(e), ephemeral=True)
            except Exception as e:
                print(f"[pin] overwrite send failed: {e}")
                return await interaction.followup.send("固定メッセージの送信に失敗しました。", ephemeral=True)

            pins = _get_pins(self.guild_id)
            pins[self.ch_id] = {
                "source_message_id":  str(self.target.id),
                "current_message_id": str(msg_id),
                "webhook_id":          str(wh.id),
            }
            _save_pins(self.guild_id, pins)
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
            pins = _get_pins(guild_id)

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
                except PinUnsupportedContentError as e:
                    return await interaction.response.edit_message(content=str(e), view=None)
                except Exception as e:
                    print(f"[pin] new pin send failed: {e}")
                    return await interaction.response.edit_message(content="固定メッセージの送信に失敗しました。", view=None)

                pins[ch_id] = {
                    "source_message_id":  str(self.target.id),
                    "current_message_id": str(msg_id),
                    "webhook_id":          str(wh.id),
                }
                _save_pins(guild_id, pins)
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
    @discord.default_permissions(manage_messages=True)
    async def pin_menu(self, ctx: discord.ApplicationContext, message: discord.Message):
        view = PinSelect(message)
        resp = await ctx.respond("操作を選択してください。", view=view, ephemeral=True)
        view.message = await resp.original_response() if hasattr(resp, "original_response") else None

    @discord.slash_command(description="現在固定中のメッセージ一覧を表示します")
    @discord.default_permissions(manage_messages=True)
    async def pin_list(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True)

        guild_id = str(ctx.guild_id)
        pins     = _get_pins(guild_id)

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
        """新着メッセージが来たら、固定済みのWebhookメッセージを一番下に送り直す予約をする
        （連投対策のため即時実行ではなくデバウンスする）"""
        if not message.guild or message.author == self.bot.user:
            return

        guild_id = str(message.guild.id)
        ch_id = str(message.channel.id)

        pins = _get_pins(guild_id)
        entry = pins.get(ch_id)
        if not entry:
            return

        # 自分の固定用Webhookからのメッセージだけは無視する（他Botのwebhookは無視しない）
        if message.webhook_id and str(message.webhook_id) == entry.get("webhook_id"):
            return

        _schedule_resend(message.channel, guild_id, ch_id)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        """③編集同期：固定の元メッセージが編集されたら、固定メッセージにも内容を反映する。
        （ルール固定・案内固定など、常に最新を保ちたい用途向け。雑談固定では誤爆しないよう
        source_message_idが一致する場合のみ反映する）"""
        if not after.guild or after.author.bot:
            return

        guild_id = str(after.guild.id)
        ch_id = str(after.channel.id)

        async with _get_lock(after.channel.id):
            pins = _get_pins(guild_id)
            entry = pins.get(ch_id)
            if not entry or entry.get("source_message_id") != str(after.id):
                return

            wh = await _find_webhook(after.channel, entry.get("webhook_id"))
            if wh is None:
                return

            try:
                await wh.edit_message(
                    int(entry["current_message_id"]),
                    content=after.content or None,
                    embeds=after.embeds,
                )
            except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
                print(f"[pin] pinned message edit sync failed: {e}")

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        """④ゴミ掃除：チャンネルが消えたら、そのチャンネルに紐づくpins.jsonの記録と
        各種キャッシュを破棄する（JSON肥大・ゴーストデータ防止）"""
        guild = getattr(channel, "guild", None)
        if guild is None:
            return

        guild_id = str(guild.id)
        ch_id = str(channel.id)

        pins = _get_pins(guild_id)
        if ch_id in pins:
            del pins[ch_id]
            _save_pins(guild_id, pins)

        _WEBHOOK_CACHE.pop(channel.id, None)
        _channel_locks.pop(channel.id, None)
        _resend_tasks.pop(channel.id, None)


def setup(bot):
    bot.add_cog(Pin(bot))
