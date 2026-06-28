import discord
from discord.ext import commands
from datetime import datetime, timezone
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import utils


# ── モーダル ──────────────────────────────────────────────────────────────────

class ReportModal(discord.ui.Modal):
    def __init__(self, target: discord.Message, anonymous: bool):
        super().__init__(title="匿名通報" if anonymous else "通報")
        self.target    = target
        self.anonymous = anonymous
        self.add_item(discord.ui.InputText(
            label="理由",
            style=discord.InputTextStyle.long,
            placeholder="通報理由を入力してください",
            max_length=500,
        ))

    async def callback(self, interaction: discord.Interaction):
        reason   = self.children[0].value
        guild_id = str(interaction.guild_id)
        cfg      = utils.get_config(guild_id)
        log_ch   = None
        if cfg.get("log_channel"):
            log_ch = interaction.guild.get_channel(int(cfg["log_channel"]))

        embed = discord.Embed(
            title="匿名通報" if self.anonymous else "通報",
            color=0xE8383D,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="対象メッセージ",
                        value=f"[ジャンプ]({self.target.jump_url})\n{self.target.content[:200] or '*(テキストなし)*'}",
                        inline=False)
        embed.add_field(name="対象ユーザー", value=self.target.author.mention)
        embed.add_field(name="理由", value=reason)

        if not self.anonymous:
            embed.add_field(name="通報者", value=interaction.user.mention)

        embed.set_footer(text=interaction.guild.name)

        if log_ch:
            await log_ch.send(embed=embed)

        await interaction.response.send_message("通報しました。", ephemeral=True)


# ── 通報種別セレクト ───────────────────────────────────────────────────────────

class ReportTypeView(discord.ui.View):
    def __init__(self, target: discord.Message):
        super().__init__(timeout=60)
        self.target = target

    @discord.ui.select(
        placeholder="通報の種類を選択",
        options=[
            discord.SelectOption(label="通常通報", value="normal"),
            discord.SelectOption(label="匿名通報", value="anon"),
        ],
    )
    async def select(self, select, interaction: discord.Interaction):
        anonymous = select.values[0] == "anon"
        await interaction.response.send_modal(ReportModal(self.target, anonymous))


# ── Cog ──────────────────────────────────────────────────────────────────────

class Report(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.message_command(name="通報する")
    async def report_menu(self, ctx: discord.ApplicationContext, message: discord.Message):
        await ctx.respond("通報の種類を選択してください。",
                          view=ReportTypeView(message), ephemeral=True)


def setup(bot):
    bot.add_cog(Report(bot))
