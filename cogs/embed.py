import discord
from discord.ext import commands


class EmbedModal(discord.ui.Modal):
    def __init__(self, original: discord.Message | None = None):
        super().__init__(title="Embed作成" if not original else "Embed編集")
        self.original = original

        self.add_item(discord.ui.InputText(label="タイトル", max_length=256))
        self.add_item(discord.ui.InputText(label="説明", style=discord.InputTextStyle.long,
                                            max_length=2000))
        self.add_item(discord.ui.InputText(label="カラー（#RRGGBB）",
                                            required=False, placeholder="#5865F2"))
        self.add_item(discord.ui.InputText(label="フッター", required=False, max_length=100))
        self.add_item(discord.ui.InputText(label="画像URL", required=False))

    async def callback(self, interaction: discord.Interaction):
        title  = self.children[0].value
        desc   = self.children[1].value
        color_str = self.children[2].value.strip().lstrip("#")
        footer = self.children[3].value
        image  = self.children[4].value

        try:
            color = int(color_str, 16) if color_str else 0x5865F2
        except ValueError:
            color = 0x5865F2

        embed = discord.Embed(title=title, description=desc, color=color)
        if footer:
            embed.set_footer(text=footer)
        if image:
            embed.set_image(url=image)

        if self.original:
            await self.original.edit(embed=embed)
            await interaction.response.send_message("編集しました。", ephemeral=True)
        else:
            await interaction.channel.send(embed=embed)
            await interaction.response.send_message("送信しました。", ephemeral=True)


class Embed(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.slash_command(description="Embedを作成して送信します")
    @discord.default_permissions(manage_messages=True)
    async def embed(self, ctx: discord.ApplicationContext):
        await ctx.send_modal(EmbedModal())

    @discord.slash_command(description="Botが送信したEmbedを編集します")
    @discord.default_permissions(manage_messages=True)
    async def embed_edit(self, ctx: discord.ApplicationContext,
                         message_id: discord.Option(str, "編集するメッセージのID")):
        try:
            msg = await ctx.channel.fetch_message(int(message_id))
        except (discord.NotFound, ValueError):
            return await ctx.respond("メッセージが見つかりません。", ephemeral=True)

        if msg.author != self.bot.user or not msg.embeds:
            return await ctx.respond("Botが送信したEmbedのみ編集できます。", ephemeral=True)

        await ctx.send_modal(EmbedModal(original=msg))


def setup(bot):
    bot.add_cog(Embed(bot))
