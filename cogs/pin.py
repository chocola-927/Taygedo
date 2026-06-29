import discord
from discord.ext import commands
from datetime import datetime, timezone
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import utils


# ── セレクト ──────────────────────────────────────────────────────────────────

class PinSelect(discord.ui.View):
    def __init__(self, target_message: discord.Message):
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
    async def select(self, interaction: discord.Interaction, select: discord.ui.Select):
        guild_id = str(interaction.guild_id)
        ch_id    = str(self.target.channel.id)
        pins     = utils.load(guild_id, "pins.json")

        if select.values[0] == "pin":
            # 既存固定を削除
            if ch_id in pins:
                old_id = pins[ch_id].get("current_message_id")
                if old_id:
                    try:
                        old_msg = await self.target.channel.fetch_message(int(old_id))
                        await old_msg.delete()
                    except discord.NotFound:
                        pass

            # Embed化して送信
            embed = _pin_embed(self.target)
            sent  = await self.target.channel.send(embed=embed)

            pins[ch_id] = {
                "source_message_id":  str(self.target.id),
                "current_message_id": str(sent.id),
            }
            utils.save(guild_id, "pins.json", pins)
            await interaction.response.edit_message(
                content="固定しました。", view=None)

        else:  # unpin
            if ch_id not in pins:
                return await interaction.response.edit_message(
                    content="固定されたメッセージがありません。", view=None)

            old_id = pins[ch_id].get("current_message_id")
            if old_id:
                try:
                    old_msg = await self.target.channel.fetch_message(int(old_id))
                    await old_msg.delete()
                except discord.NotFound:
                    pass

            del pins[ch_id]
            utils.save(guild_id, "pins.json", pins)
            await interaction.response.edit_message(
                content="固定を解除しました。", view=None)


# ── ヘルパー ──────────────────────────────────────────────────────────────────

def _pin_embed(msg: discord.Message):
    embed = discord.Embed(
        description=msg.content or "*（テキストなし）*",
        color=0xF0B132,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_author(name=msg.author.display_name,
                     icon_url=msg.author.display_avatar.url)
    if msg.attachments:
        embed.set_image(url=msg.attachments[0].url)
    embed.set_footer(text=f"#{msg.channel.name}")
    return embed


# ── Cog ──────────────────────────────────────────────────────────────────────

class Pin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # Context Menu
    @discord.message_command(name="メッセージを固定")
    async def pin_menu(self, ctx: discord.ApplicationContext, message: discord.Message):
        view = PinSelect(message)
        await ctx.respond("操作を選択してください。", view=view, ephemeral=True)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        """固定Botメッセージが消されたら自動解除"""
        if not message.guild or message.author != self.bot.user:
            return

        guild_id = str(message.guild.id)
        ch_id    = str(message.channel.id)
        pins     = utils.load(guild_id, "pins.json")

        if ch_id in pins and pins[ch_id].get("current_message_id") == str(message.id):
            del pins[ch_id]
            utils.save(guild_id, "pins.json", pins)


def setup(bot):
    bot.add_cog(Pin(bot))
