import asyncio
import discord
from discord.ext import commands
import re, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import utils


# ── 絵文字抽出ヘルパー ────────────────────────────────────────────────────────

def _extract_emoji(label: str) -> tuple[str | None, str | None]:
    """ラベル先頭の絵文字を抽出して (emoji, text) を返す。
    labelが絵文字のみの場合は text=None を返す（役割の重複を避けるため）。
    """
    label = label.strip()

    # Unicodeカスタム絵文字 <:name:id> or <a:name:id>
    m = re.match(r"^(<a?:\w+:\d+>)\s*(.*)$", label)
    if m:
        rest = m.group(2).strip()
        return m.group(1), (rest or None)

    # Unicode絵文字（1〜2文字）
    m = re.match(
        r"^([\U0001F000-\U0001FFFF]|[\U00002600-\U000027BF]|"
        r"[\U0001F300-\U0001F9FF][\uFE0F]?)\s*(.*)$",
        label
    )
    if m:
        rest = m.group(2).strip()
        return m.group(1), (rest or None)

    return None, (label or None)


# ── ボタンスタイル変換 ─────────────────────────────────────────────────────────

STYLE_MAP = {
    "青": discord.ButtonStyle.primary,
    "緑": discord.ButtonStyle.success,
    "赤": discord.ButtonStyle.danger,
    "グレー": discord.ButtonStyle.secondary,
}


# ── Embed説明文の組み立て ─────────────────────────────────────────────────────

def _build_description(guild: discord.Guild, base: str | None, buttons: list[dict]) -> str | None:
    """パネル作成時の説明文(base) + 現在登録されているロール一覧、を結合して返す"""
    lines = []
    if base:
        lines.append(base)

    role_lines = []
    for b in buttons:
        role = guild.get_role(b["role_id"])
        if not role:
            # 削除済みロールは一覧から静かに除外
            continue
        parts = []
        if b.get("emoji"):
            parts.append(b["emoji"])
        if b.get("custom_label"):
            parts.append(b["custom_label"])
        parts.append(role.mention)
        role_lines.append("・" + " ".join(parts))

    if role_lines:
        if lines:
            lines.append("")
        lines.append("**受け取れるロール**")
        lines.extend(role_lines)

    return "\n".join(lines) if lines else None


def _build_button_label(guild: discord.Guild, b: dict) -> str | None:
    """ボタン表示用のラベルを組み立てる。ロールが見つからない場合はNoneを返す"""
    role = guild.get_role(b["role_id"])
    if not role:
        return None
    if b.get("custom_label"):
        text = f'{b["custom_label"]} {role.name}'
    else:
        text = role.name
    return text[:80]  # discordのボタンラベル上限


# ── ロールボタン ──────────────────────────────────────────────────────────────

class RoleButton(discord.ui.Button):
    def __init__(self, role_id: int, label: str, emoji=None,
                 style=discord.ButtonStyle.primary):
        super().__init__(
            label=label,
            emoji=emoji,
            style=style,
            custom_id=f"role:{role_id}",
        )
        self.role_id = role_id

    async def callback(self, interaction: discord.Interaction):
        role = interaction.guild.get_role(self.role_id)
        if not role:
            return await interaction.response.send_message(
                "ロールが見つかりません。", ephemeral=True)

        try:
            if role in interaction.user.roles:
                await interaction.user.remove_roles(role)
                await interaction.response.send_message(
                    f"🗑️ **{role.name}** を外しました。", ephemeral=True)
            else:
                await interaction.user.add_roles(role)
                await interaction.response.send_message(
                    f"✅ **{role.name}** を付与しました。", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(
                "⚠️ 権限不足のためロールを変更できませんでした。"
                "Botのロール順位がこのロールより上にあるか確認してください。",
                ephemeral=True)


# ── パネルView ────────────────────────────────────────────────────────────────

class RolePanelView(discord.ui.View):
    def __init__(self, guild: discord.Guild, buttons: list[dict]):
        super().__init__(timeout=None)
        for b in buttons:
            label = _build_button_label(guild, b)
            if label is None:
                # ロールが削除済みなどで解決できない場合はボタンごと表示しない
                continue
            self.add_item(RoleButton(
                role_id=b["role_id"],
                label=label,
                emoji=b.get("emoji"),
                style=STYLE_MAP.get(b.get("color", "青"), discord.ButtonStyle.primary),
            ))


# ── パネル作成モーダル ────────────────────────────────────────────────────────

class RolePanelModal(discord.ui.Modal):
    def __init__(self, guild_id: str, channel: discord.TextChannel):
        super().__init__(title="ロールパネル作成")
        self.guild_id = guild_id
        self.channel  = channel

        self.add_item(discord.ui.InputText(
            label="タイトル",
            placeholder="例: 受け取りたいロールを選んでね",
            max_length=50,
        ))
        self.add_item(discord.ui.InputText(
            label="説明",
            placeholder="例: ボタンを押すとロールが付与・剥奪されます",
            style=discord.InputTextStyle.paragraph,
            required=False,
            max_length=200,
        ))

    async def callback(self, interaction: discord.Interaction):
        title       = self.children[0].value.strip()
        description = self.children[1].value.strip() or None

        panels = utils.load(self.guild_id, "role_panels.json")

        if title in panels:
            return await interaction.response.send_message(
                f"「{title}」という名前のパネルはすでに存在します。", ephemeral=True)

        embed = discord.Embed(
            title=title,
            description=description,
            color=0x5865F2,
        )
        msg = await self.channel.send(embed=embed)

        panels[title] = {
            "message_id":  str(msg.id),
            "channel_id":  str(self.channel.id),
            "description": description,   # ロール一覧を除いた元の説明文（再生成の基点）
            "buttons":     [],
        }
        utils.save(self.guild_id, "role_panels.json", panels)

        await interaction.response.send_message(
            f"パネル「{title}」を設置しました。\n`/add_role` でボタンを追加できます。",
            ephemeral=True)


# ── Cog ──────────────────────────────────────────────────────────────────────

class RolePanel(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        """Bot起動時にPersistent Viewを復元しつつ、消えているパネルを掃除する"""
        for guild in self.bot.guilds:
            guild_id = str(guild.id)
            panels   = utils.load(guild_id, "role_panels.json")
            changed  = False

            for title, data in list(panels.items()):
                channel = guild.get_channel(int(data["channel_id"]))
                if not channel:
                    # キャッシュに無い＝「削除された」か「権限的に見えていないだけ」の
                    # どちらか判別できないので、APIに直接問い合わせて確定させる
                    try:
                        channel = await self.bot.fetch_channel(int(data["channel_id"]))
                    except discord.NotFound:
                        # 本当に存在しない → JSONのゴミを掃除
                        del panels[title]
                        changed = True
                        continue
                    except discord.Forbidden:
                        # 存在はするが閲覧権限がない → 削除しない
                        continue
                    except discord.HTTPException:
                        continue

                try:
                    msg = await channel.fetch_message(int(data["message_id"]))
                except discord.NotFound:
                    # メッセージが実際に存在しない → JSONのゴミを掃除
                    del panels[title]
                    changed = True
                    continue
                except discord.Forbidden:
                    # 閲覧権限がないだけかもしれないので削除しない
                    continue
                except discord.HTTPException:
                    continue

                if data.get("buttons"):
                    view = RolePanelView(guild, data["buttons"])
                    self.bot.add_view(view, message_id=msg.id)

                await asyncio.sleep(0.5)  # レート制限対策

            if changed:
                utils.save(guild_id, "role_panels.json", panels)

    async def _refresh_panel_message(self, guild: discord.Guild, title: str, data: dict) -> bool:
        """パネルのEmbed/Viewを現在のbuttons内容で再描画する。成功したらTrue"""
        channel = guild.get_channel(int(data["channel_id"]))
        if not channel:
            return False

        try:
            msg = await channel.fetch_message(int(data["message_id"]))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return False

        embed = discord.Embed(
            title=title,
            description=_build_description(guild, data.get("description"), data["buttons"]),
            color=0x5865F2,
        )
        view = RolePanelView(guild, data["buttons"])
        self.bot.add_view(view, message_id=msg.id)

        try:
            await msg.edit(embed=embed, view=view)
        except discord.HTTPException:
            return False

        return True

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        """ロールが削除されたら、パネル内の対応ボタンをJSONごと消してメッセージを更新する"""
        guild    = role.guild
        guild_id = str(guild.id)
        panels   = utils.load(guild_id, "role_panels.json")
        changed  = False

        for title, data in panels.items():
            before = len(data["buttons"])
            data["buttons"] = [b for b in data["buttons"] if b["role_id"] != role.id]
            if len(data["buttons"]) != before:
                changed = True
                await self._refresh_panel_message(guild, title, data)

        if changed:
            utils.save(guild_id, "role_panels.json", panels)

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        """パネルメッセージが手動削除されたら、対応するJSONエントリを自動削除する"""
        if not payload.guild_id:
            return

        guild_id = str(payload.guild_id)
        panels   = utils.load(guild_id, "role_panels.json")

        target_title = None
        for title, data in panels.items():
            if str(data.get("message_id")) == str(payload.message_id):
                target_title = title
                break

        if target_title:
            del panels[target_title]
            utils.save(guild_id, "role_panels.json", panels)

    @discord.slash_command(description="ロールパネルを設置します")
    @discord.default_permissions(administrator=True)
    async def role_panel(self, ctx: discord.ApplicationContext):
        modal = RolePanelModal(str(ctx.guild_id), ctx.channel)
        await ctx.send_modal(modal)

    @discord.slash_command(description="ロールパネルにボタンを追加します")
    @discord.default_permissions(administrator=True)
    async def add_role(self, ctx: discord.ApplicationContext,
                       title: discord.Option(str, "対象パネルのタイトル"),
                       role: discord.Option(discord.Role, "付与・剥奪するロール"),
                       label: discord.Option(str, "ボタンの追加ラベル（任意・先頭に絵文字可／ロール名は自動で付きます）",
                                             required=False, default=None),
                       color: discord.Option(str, "ボタンの色",
                                             choices=["青", "緑", "赤", "グレー"],
                                             default="青")):
        await ctx.defer(ephemeral=True)

        guild_id = str(ctx.guild_id)
        panels   = utils.load(guild_id, "role_panels.json")

        if title not in panels:
            return await ctx.respond(
                f"「{title}」というパネルが見つかりません。", ephemeral=True)

        data = panels[title]

        if len(data["buttons"]) >= 25:
            return await ctx.respond(
                "ボタンは最大25個までです。", ephemeral=True)

        # 同じロールが既に登録されていないか確認
        if any(b["role_id"] == role.id for b in data["buttons"]):
            return await ctx.respond(
                f"**{role.name}** はすでにこのパネルに登録されています。", ephemeral=True)

        # 付与不可能なロールを弾く
        if role.is_default():
            return await ctx.respond(
                "@everyone ロールは登録できません。", ephemeral=True)
        if role.managed:
            return await ctx.respond(
                f"**{role.name}** はBotや連携サービスが管理するロールのため登録できません。",
                ephemeral=True)
        if role >= ctx.guild.me.top_role:
            return await ctx.respond(
                f"**{role.name}** はBotのロールと同格か、それより上位に設定されているため"
                "付与・剥奪できません。ロール順を確認してください。",
                ephemeral=True)

        # 絵文字・カスタムラベル抽出
        emoji, custom_label = (None, None)
        if label:
            emoji, custom_label = _extract_emoji(label)

        # ボタン情報を保存
        data["buttons"].append({
            "role_id":      role.id,
            "custom_label": custom_label,
            "emoji":        emoji,
            "color":        color,
        })
        utils.save(guild_id, "role_panels.json", panels)

        # パネルメッセージを更新
        ok = await self._refresh_panel_message(ctx.guild, title, data)
        if not ok:
            return await ctx.respond(
                "パネルメッセージの更新に失敗しました（チャンネル/メッセージが見つからないか、権限不足です）。",
                ephemeral=True)

        await ctx.respond(
            f"「{title}」に **{role.name}** のボタンを追加しました。", ephemeral=True)


def setup(bot):
    bot.add_cog(RolePanel(bot))
