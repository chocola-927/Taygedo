import discord
from discord.ext import commands
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import utils

LOG_KEYS = {
    "メッセージ削除": "message_delete",
    "メッセージ編集": "message_edit",
    "参加":           "member_join",
    "退出":           "member_leave",
    "BAN":            "ban",
    "Kick":           "kick",
    "タイムアウト":   "timeout",
    "警告":           "warn",
    "ロール付与":     "role_add",
    "ロール削除":     "role_remove",
    "チケット":       "ticket",
}

# LOG_KEYS の逆引き（value -> label）
_KEY_TO_LABEL = {v: k for k, v in LOG_KEYS.items()}


class Settings(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _save(self, guild_id, **kwargs):
        cfg = utils.load(guild_id, "config.json")
        cfg.update(kwargs)
        utils.save(guild_id, "config.json", cfg)

    @discord.slash_command(description="ログチャンネルを設定します")
    @discord.default_permissions(administrator=True)
    async def set_log(self, ctx: discord.ApplicationContext,
                      channel: discord.Option(discord.TextChannel, "ログを送るチャンネル")):
        self._save(str(ctx.guild_id), log_channel=str(channel.id))
        await ctx.respond(f"ログチャンネルを {channel.mention} に設定しました。", ephemeral=True)

    @discord.slash_command(description="入室挨拶チャンネルを設定します")
    @discord.default_permissions(administrator=True)
    async def set_welcome(self, ctx: discord.ApplicationContext,
                          channel: discord.Option(discord.TextChannel, "挨拶を送るチャンネル")):
        self._save(str(ctx.guild_id), welcome_channel=str(channel.id))
        await ctx.respond(f"Welcomeチャンネルを {channel.mention} に設定しました。", ephemeral=True)

    @discord.slash_command(description="管理者ロールを設定します")
    @discord.default_permissions(administrator=True)
    async def set_admin(self, ctx: discord.ApplicationContext,
                        role: discord.Option(discord.Role, "管理者ロール")):
        self._save(str(ctx.guild_id), admin_role=str(role.id))
        await ctx.respond(f"管理者ロールを {role.mention} に設定しました。", ephemeral=True)

    @discord.slash_command(description="ログ種別をON/OFFします")
    @discord.default_permissions(administrator=True)
    async def log_setting(self, ctx: discord.ApplicationContext):
        guild_id = str(ctx.guild_id)
        cfg      = utils.load(guild_id, "config.json")
        logs     = cfg.get("logs", {k: True for k in LOG_KEYS.values()})

        options = [
            discord.SelectOption(
                label=label,
                value=key,
                description="現在: ON" if logs.get(key, True) else "現在: OFF",
            )
            for label, key in LOG_KEYS.items()
        ]

        view = LogToggleView(guild_id, options)
        await ctx.respond("切り替えるログ種別を選択してください。", view=view, ephemeral=True)


class LogToggleView(discord.ui.View):
    def __init__(self, guild_id: str, options: list):
        super().__init__(timeout=60)
        self.guild_id = guild_id
        select = discord.ui.Select(
            placeholder="切り替えるログ種別を選択",
            options=options,
            min_values=1,
            max_values=len(options),
        )
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, interaction: discord.Interaction):
        cfg  = utils.load(self.guild_id, "config.json")
        logs = cfg.get("logs", {})
        for key in interaction.data["values"]:
            logs[key] = not logs.get(key, True)
        cfg["logs"] = logs
        utils.save(self.guild_id, "config.json", cfg)

        result = "\n".join(
            f"{_KEY_TO_LABEL.get(k, k)}: {'ON' if logs.get(k, True) else 'OFF'}"
            for k in interaction.data["values"]
        )
        await interaction.response.edit_message(
            content=f"設定を変更しました。\n```\n{result}\n```", view=None)


def setup(bot):
    bot.add_cog(Settings(bot))
