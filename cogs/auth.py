```python
import discord
from discord.ext import commands
import random
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import utils


# ── 計算問題生成 ──────────────────────────────────────────────────────────────

def _make_question():
    a, b = random.randint(1, 20), random.randint(1, 20)
    op = random.choice(["+", "-", "*"])

    if op == "+":
        ans = a + b
    elif op == "-":
        ans = a - b
    else:
        ans = a * b

    return f"{a} {op} {b}", ans


# ── 認証ロール付与処理 ────────────────────────────────────────────────────────

async def _add_auth_role(interaction: discord.Interaction):
    """認証時のロール付与を共通処理する。"""

    guild = interaction.guild
    if guild is None:
        return await interaction.response.send_message(
            "この機能はサーバー内でのみ使用できます。",
            ephemeral=True,
        )

    # Bot自身を取得
    me = guild.me
    if me is None:
        return await interaction.response.send_message(
            "Botの情報を取得できませんでした。",
            ephemeral=True,
        )

    # 設定取得
    guild_id = str(guild.id)
    cfg = utils.get_config(guild_id)

    role_id = cfg.get("auth_role")

    if not role_id:
        return await interaction.response.send_message(
            "認証ロールが設定されていません。管理者に連絡してください。",
            ephemeral=True,
        )

    # ロール取得
    try:
        role = guild.get_role(int(role_id))
    except (TypeError, ValueError):
        role = None

    if role is None:
        return await interaction.response.send_message(
            "認証ロールが見つかりません。管理者に連絡してください。",
            ephemeral=True,
        )

    # すでに認証済み
    if role in interaction.user.roles:
        return await interaction.response.send_message(
            "すでに認証済みです。",
            ephemeral=True,
        )

    # ── Bot側の権限チェック ────────────────────────────────────────────────

    if not me.guild_permissions.manage_roles:
        return await interaction.response.send_message(
            "現在、Botに「ロールの管理」権限がないため認証できません。"
            "管理者に確認してください。",
            ephemeral=True,
        )

    # @everyone は付与不可
    if role.is_default():
        return await interaction.response.send_message(
            "認証ロールに @everyone を設定することはできません。",
            ephemeral=True,
        )

    # Botが管理するロールは付与不可
    if role.managed:
        return await interaction.response.send_message(
            "このロールはBotによって管理されているため付与できません。",
            ephemeral=True,
        )

    # Botの最上位ロール以下でなければ付与不可
    if role >= me.top_role:
        return await interaction.response.send_message(
            "認証ロールがBotの最上位ロール以上にあるため、"
            "ロールを付与できません。\n"
            "Botのロールを認証ロールより上に移動してください。",
            ephemeral=True,
        )

    # 実際にロール付与
    try:
        await interaction.user.add_roles(
            role,
            reason="認証システムによる認証ロール付与",
        )
    except discord.Forbidden:
        return await interaction.response.send_message(
            "Botにロールを付与する権限がないため、認証に失敗しました。",
            ephemeral=True,
        )
    except discord.HTTPException:
        return await interaction.response.send_message(
            "ロールの付与中にDiscord側でエラーが発生しました。",
            ephemeral=True,
        )

    await interaction.response.send_message(
        "✅ 認証完了しました！",
        ephemeral=True,
    )


# ── ボタン式認証 ──────────────────────────────────────────────────────────────

class AuthButtonView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="認証",
        style=discord.ButtonStyle.success,
        custom_id="auth:button",
    )
    async def auth(
        self,
        button: discord.ui.Button,
        interaction: discord.Interaction,
    ):
        await _add_auth_role(interaction)


# ── 計算式認証 ────────────────────────────────────────────────────────────────

class AuthCalcModal(discord.ui.Modal):
    def __init__(self, question: str, answer: int):
        super().__init__(title="認証")

        self.answer = answer

        self.add_item(
            discord.ui.InputText(
                label=f"{question} = ?",
                placeholder="答えを入力してください",
                max_length=10,
            )
        )

    async def callback(self, interaction: discord.Interaction):
        try:
            user_ans = int(self.children[0].value.strip())
        except ValueError:
            return await interaction.response.send_message(
                "❌ 数字を入力してください。",
                ephemeral=True,
            )

        if user_ans != self.answer:
            return await interaction.response.send_message(
                "❌ 不正解です。もう一度試してください。",
                ephemeral=True,
            )

        await _add_auth_role(interaction)


class AuthCalcView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="認証",
        style=discord.ButtonStyle.success,
        custom_id="auth:calc",
    )
    async def auth(
        self,
        button: discord.ui.Button,
        interaction: discord.Interaction,
    ):
        question, answer = _make_question()

        await interaction.response.send_modal(
            AuthCalcModal(question, answer)
        )


# ── Cog ──────────────────────────────────────────────────────────────────────

class Auth(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        # Bot再起動後も既存パネルのボタンを動作させる
        bot.add_view(AuthButtonView())
        bot.add_view(AuthCalcView())

    @discord.slash_command(
        description="認証パネルを設置します"
    )
    @discord.default_permissions(
        manage_roles=True
    )
    async def auth_panel(
        self,
        ctx: discord.ApplicationContext,
        role: discord.Option(
            discord.Role,
            "認証後に付与するロール",
        ),
        kind: discord.Option(
            str,
            "認証の種類",
            choices=["ボタン式", "計算式"],
        ),
        title: discord.Option(
            str,
            "Embedのタイトル",
            default="認証",
        ),
        description: discord.Option(
            str,
            "Embedの説明",
            default="下のボタンを押して認証してください。",
        ),
    ):
        guild = ctx.guild

        if guild is None:
            return await ctx.respond(
                "このコマンドはサーバー内でのみ使用できます。",
                ephemeral=True,
            )

        me = guild.me

        if me is None:
            return await ctx.respond(
                "Botの情報を取得できませんでした。",
                ephemeral=True,
            )

        # ── 実行者の権限 ───────────────────────────────────────────────────

        if not ctx.author.guild_permissions.manage_roles:
            return await ctx.respond(
                "このコマンドには「ロールの管理」権限が必要です。",
                ephemeral=True,
            )

        # ── Botの権限 ─────────────────────────────────────────────────────

        missing = []

        # サーバー全体の権限
        if not me.guild_permissions.manage_roles:
            missing.append("ロールの管理")

        # 現在のチャンネルでの権限
        ch_perms = ctx.channel.permissions_for(me)

        if not ch_perms.view_channel:
            missing.append("チャンネルを見る")

        if not ch_perms.send_messages:
            missing.append("メッセージを送信")

        if not ch_perms.embed_links:
            missing.append("埋め込みリンク")

        if missing:
            return await ctx.respond(
                "Botに次の権限が不足しています:\n"
                + "\n".join(f"・{perm}" for perm in missing),
                ephemeral=True,
            )

        # ── 認証ロールのチェック ─────────────────────────────────────────

        # @everyone
        if role.is_default():
            return await ctx.respond(
                "「@everyone」は認証ロールに指定できません。",
                ephemeral=True,
            )

        # Bot等によって管理されているロール
        if role.managed:
            return await ctx.respond(
                "このロールはBotなどによって管理されているため、"
                "認証ロールには指定できません。",
                ephemeral=True,
            )

        # Botの最上位ロールより上 / 同じ
        if role >= me.top_role:
            return await ctx.respond(
                "指定したロールがBotの最上位ロール以上にあります。\n"
                "Botのロールを認証ロールより上に移動してください。",
                ephemeral=True,
            )

        # 実行者自身の最上位ロール以上のロールを指定できない
        # サーバーオーナーは例外
        if (
            ctx.author != guild.owner
            and role >= ctx.author.top_role
        ):
            return await ctx.respond(
                "あなたの最上位ロール以上のロールは、"
                "認証ロールに指定できません。",
                ephemeral=True,
            )

        # ── 設定保存 ─────────────────────────────────────────────────────

        guild_id = str(guild.id)

        cfg = utils.load(guild_id, "config.json")
        cfg["auth_role"] = str(role.id)
        utils.save(guild_id, "config.json", cfg)

        # ── パネル作成 ───────────────────────────────────────────────────

        view = (
            AuthButtonView()
            if kind == "ボタン式"
            else AuthCalcView()
        )

        embed = discord.Embed(
            title=title,
            description=description,
            color=0x00A960,
        )

        try:
            await ctx.channel.send(
                embed=embed,
                view=view,
            )
        except discord.Forbidden:
            return await ctx.respond(
                "Botにこのチャンネルへパネルを設置する権限がありません。",
                ephemeral=True,
            )
        except discord.HTTPException:
            return await ctx.respond(
                "認証パネルの設置中にDiscord側でエラーが発生しました。",
                ephemeral=True,
            )

        await ctx.respond(
            "認証パネルを設置しました。",
            ephemeral=True,
        )


def setup(bot):
    bot.add_cog(Auth(bot))
```
