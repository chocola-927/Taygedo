import discord
from discord.ext import commands
from datetime import datetime, timezone
import random, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import utils


# ── 計算問題生成 ──────────────────────────────────────────────────────────────

def _make_question():
    a, b = random.randint(1, 20), random.randint(1, 20)
    op   = random.choice(["+", "-", "*"])
    if op == "+":
        ans = a + b
    elif op == "-":
        ans = a - b
    else:
        ans = a * b
    return f"{a} {op} {b}", ans


# ── ボタン式認証 ──────────────────────────────────────────────────────────────

class AuthButtonView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="認証", style=discord.ButtonStyle.success,
                       custom_id="auth:button")
    async def auth(self, button, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        cfg      = utils.get_config(guild_id)
        role_id  = cfg.get("auth_role")
        if not role_id:
            return await interaction.response.send_message(
                "認証ロールが設定されていません。管理者に連絡してください。", ephemeral=True)

        role = interaction.guild.get_role(int(role_id))
        if not role:
            return await interaction.response.send_message(
                "ロールが見つかりません。", ephemeral=True)

        if role in interaction.user.roles:
            return await interaction.response.send_message(
                "すでに認証済みです。", ephemeral=True)

        await interaction.user.add_roles(role)
        await interaction.response.send_message("✅ 認証完了しました！", ephemeral=True)


# ── 計算式認証 ────────────────────────────────────────────────────────────────

class AuthCalcModal(discord.ui.Modal):
    def __init__(self, question: str, answer: int):
        super().__init__(title="認証")
        self.answer = answer
        self.add_item(discord.ui.InputText(
            label=f"{question} = ?",
            placeholder="答えを入力してください",
            max_length=10,
        ))

    async def callback(self, interaction: discord.Interaction):
        try:
            user_ans = int(self.children[0].value.strip())
        except ValueError:
            return await interaction.response.send_message(
                "❌ 数字を入力してください。", ephemeral=True)

        if user_ans != self.answer:
            return await interaction.response.send_message(
                "❌ 不正解です。もう一度試してください。", ephemeral=True)

        guild_id = str(interaction.guild_id)
        cfg      = utils.get_config(guild_id)
        role_id  = cfg.get("auth_role")
        if not role_id:
            return await interaction.response.send_message(
                "認証ロールが設定されていません。", ephemeral=True)

        role = interaction.guild.get_role(int(role_id))
        if not role:
            return await interaction.response.send_message(
                "ロールが見つかりません。", ephemeral=True)

        if role in interaction.user.roles:
            return await interaction.response.send_message(
                "すでに認証済みです。", ephemeral=True)

        await interaction.user.add_roles(role)
        await interaction.response.send_message("✅ 認証完了しました！", ephemeral=True)


class AuthCalcView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="認証", style=discord.ButtonStyle.success,
                       custom_id="auth:calc")
    async def auth(self, button, interaction: discord.Interaction):
        question, answer = _make_question()
        await interaction.response.send_modal(AuthCalcModal(question, answer))


# ── Cog ──────────────────────────────────────────────────────────────────────

class Auth(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        bot.add_view(AuthButtonView())
        bot.add_view(AuthCalcView())

    @discord.slash_command(description="認証パネルを設置します")
    @discord.default_permissions(administrator=True)
    async def auth_panel(self, ctx: discord.ApplicationContext,
                         role: discord.Option(discord.Role, "認証後に付与するロール"),
                         kind: discord.Option(str, "認証の種類",
                                              choices=["ボタン式", "計算式"]),
                         title: discord.Option(str, "Embedのタイトル",
                                               default="認証"),
                         description: discord.Option(str, "Embedの説明",
                                                     default="下のボタンを押して認証してください。")):
        await ctx.defer(ephemeral=True)

        # auth_role を config に保存
        guild_id = str(ctx.guild_id)
        cfg      = utils.load(guild_id, "config.json")
        cfg["auth_role"] = str(role.id)
        utils.save(guild_id, "config.json", cfg)

        view  = AuthButtonView() if kind == "ボタン式" else AuthCalcView()
        embed = discord.Embed(
            title=title,
            description=description,
            color=0x00A960,
            timestamp=datetime.now(timezone.utc),
        )
        await ctx.channel.send(embed=embed, view=view)
        await ctx.respond("認証パネルを設置しました。", ephemeral=True)


def setup(bot):
    bot.add_cog(Auth(bot))
