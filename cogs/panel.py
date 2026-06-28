import discord
from discord.ext import commands
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import utils


class Panel(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.slash_command(description="チケットパネルを設置します")
    @discord.default_permissions(administrator=True)
    async def ticket_panel(self, ctx: discord.ApplicationContext,
                           category: discord.Option(discord.CategoryChannel, "チケットを作成するカテゴリ"),
                           kind: discord.Option(str, "種類", choices=["通常", "匿名"])):
        await ctx.defer(ephemeral=True)

        if kind == "通常":
            from cogs.ticket import TicketOpenButton
            view     = TicketOpenButton()
            key      = "ticket"
            label    = "チケット"
            color    = 0x5865F2
        else:
            from cogs.anon_ticket import AnonTicketOpenButton
            view     = AnonTicketOpenButton()
            key      = "anon_ticket"
            label    = "匿名チケット"
            color    = 0x5865F2

        embed = discord.Embed(
            title=f"{label}パネル",
            description=f"下のボタンから{label}を開くことができます。",
            color=color,
        )
        msg = await ctx.channel.send(embed=embed, view=view)

        # panels.json に保存
        guild_id = str(ctx.guild_id)
        panels   = utils.load(guild_id, "panels.json")
        panels[key] = {
            "channel_id":  str(ctx.channel_id),
            "message_id":  str(msg.id),
            "category_id": str(category.id),
        }
        utils.save(guild_id, "panels.json", panels)

        await ctx.respond("パネルを設置しました。", ephemeral=True)


def setup(bot):
    bot.add_cog(Panel(bot))
