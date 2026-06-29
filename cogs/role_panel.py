import discord
from discord.ext import commands
import re, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import utils


# ── 絵文字抽出ヘルパー ────────────────────────────────────────────────────────

def _extract_emoji(label: str) -> tuple[str | None, str]:
    """ラベル先頭の絵文字を抽出して (emoji, text) を返す"""
    # Unicodeカスタム絵文字 <:name:id> or <a:name:id>
    m = re.match(r"^(<a?:\w+:\d+>)\s*(.*)$", label.strip())
    if m:
        return m.group(1), m.group(2).strip() or m.group(1)

    # Unicode絵文字（1〜2文字）
    m = re.match(
        r"^([\U0001F000-\U0001FFFF]|[\U00002600-\U000027BF]|"
        r"[\U0001F300-\U0001F9FF][\uFE0F]?)\s*(.*)$",
        label.strip()
    )
    if m:
        return m.group(1), m.group(2).strip() or m.group(1)

    return None, label.strip()


# ── ボタンスタイル変換 ─────────────────────────────────────────────────────────

STYLE_MAP = {
    "青": discord.ButtonStyle.primary,
    "緑": discord.ButtonStyle.success,
    "赤": discord.ButtonStyle.danger,
    "グレー": discord.ButtonStyle.secondary,
}


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

        if role in interaction.user.roles:
            await interaction.user.remove_roles(role)
            await interaction.response.send_message(
                f"🗑️ **{role.name}** を外しました。", ephemeral=True)
        else:
            await interaction.user.add_roles(role)
            await interaction.response.send_message(
                f"✅ **{role.name}** を付与しました。", ephemeral=True)


# ── パネルView ────────────────────────────────────────────────────────────────

class RolePanelView(discord.ui.View):
    def __init__(self, buttons: list[dict]):
        super().__init__(timeout=None)
        for b in buttons:
            self.add_item(RoleButton(
                role_id=b["role_id"],
                label=b["label"],
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
            "message_id": str(msg.id),
            "channel_id": str(self.channel.id),
            "buttons":    [],
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
        """Bot起動時にPersistent Viewを復元"""
        for guild in self.bot.guilds:
            guild_id = str(guild.id)
            panels   = utils.load(guild_id, "role_panels.json")
            for title, data in panels.items():
                if data.get("buttons"):
                    self.bot.add_view(
                        RolePanelView(data["buttons"]),
                        message_id=int(data["message_id"]),
                    )

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
                       label: discord.Option(str, "ボタンのラベル（先頭に絵文字可）"),
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

        # 絵文字抽出
        emoji, text = _extract_emoji(label)

        # ボタン情報を保存
        data["buttons"].append({
            "role_id": role.id,
            "label":   text,
            "emoji":   emoji,
            "color":   color,
        })
        utils.save(guild_id, "role_panels.json", panels)

        # パネルメッセージを更新
        ch = ctx.guild.get_channel(int(data["channel_id"]))
        if not ch:
            return await ctx.respond("チャンネルが見つかりません。", ephemeral=True)

        try:
            msg = await ch.fetch_message(int(data["message_id"]))
        except discord.NotFound:
            return await ctx.respond("パネルメッセージが見つかりません。", ephemeral=True)

        view = RolePanelView(data["buttons"])
        self.bot.add_view(view, message_id=msg.id)
        await msg.edit(view=view)

        await ctx.respond(
            f"「{title}」に **{role.name}** のボタンを追加しました。", ephemeral=True)

    @discord.slash_command(description="ロールパネルを削除します")
    @discord.default_permissions(administrator=True)
    async def delete_role_panel(self, ctx: discord.ApplicationContext,
                                title: discord.Option(str, "削除するパネルのタイトル")):
        await ctx.defer(ephemeral=True)

        guild_id = str(ctx.guild_id)
        panels   = utils.load(guild_id, "role_panels.json")

        if title not in panels:
            return await ctx.respond(
                f"「{title}」というパネルが見つかりません。", ephemeral=True)

        data = panels[title]
        ch   = ctx.guild.get_channel(int(data["channel_id"]))
        if ch:
            try:
                msg = await ch.fetch_message(int(data["message_id"]))
                await msg.delete()
            except discord.NotFound:
                pass

        del panels[title]
        utils.save(guild_id, "role_panels.json", panels)
        await ctx.respond(f"パネル「{title}」を削除しました。", ephemeral=True)


def setup(bot):
    bot.add_cog(RolePanel(bot))
