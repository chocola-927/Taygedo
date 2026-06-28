import discord
from discord.ext import commands


class Utility(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.slash_command(description="ユーザーのアイコンを取得します")
    async def avatar(self, ctx: discord.ApplicationContext,
                     user: discord.Option(discord.Member, "対象ユーザー", required=False)):
        target = user or ctx.author
        embed  = discord.Embed(color=0x5865F2)
        embed.set_author(name=target.display_name)
        embed.set_image(url=target.display_avatar.url)
        await ctx.respond(embed=embed, ephemeral=True)

    @discord.slash_command(description="ユーザーのバナー（背景）を取得します")
    async def background(self, ctx: discord.ApplicationContext,
                         user: discord.Option(discord.Member, "対象ユーザー", required=False)):
        target    = user or ctx.author
        fetched   = await ctx.bot.fetch_user(target.id)
        if not fetched.banner:
            return await ctx.respond("バナーが設定されていません。", ephemeral=True)
        embed = discord.Embed(color=0x5865F2)
        embed.set_author(name=target.display_name)
        embed.set_image(url=fetched.banner.url)
        await ctx.respond(embed=embed, ephemeral=True)


def setup(bot):
    bot.add_cog(Utility(bot))
