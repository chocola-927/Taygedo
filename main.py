import os, traceback, signal, asyncio, hashlib, json
import aiohttp
from datetime import datetime, timezone
import discord
from dotenv import load_dotenv
from keep_alive import keep_alive
import utils

# SIGTERMを無視してbotを生かし続ける
signal.signal(signal.SIGTERM, signal.SIG_IGN)

load_dotenv()
TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
ERROR_WEBHOOK_URL = os.getenv("ERROR_WEBHOOK_URL")  # Discord本体が不調な時の保険ルート

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = discord.Bot(intents=intents)


# ── コマンド定義のハッシュ管理（変更が無ければ同期をスキップする） ───────────────
_GLOBAL_KEY = "_global"  # ギルド単位ではないグローバル設定用の擬似guild_id


def _normalize(obj):
    """dict/list内の順序が不安定な要素(set由来のリスト等)を正規化する。
    dictはkeyでソートされたJSON化に任せるが、list（特にcontexts/integration_typesなど
    setから変換されたもの）は要素を比較可能な文字列キーでソートして順序を固定する。
    """
    if isinstance(obj, dict):
        return {k: _normalize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        normalized = [_normalize(v) for v in obj]
        try:
            return sorted(normalized, key=lambda v: json.dumps(v, sort_keys=True))
        except TypeError:
            return normalized
    return obj


def _compute_commands_hash() -> str:
    """現在登録されている全スラッシュコマンドの定義からハッシュを計算する"""
    defs = []
    for cmd in bot.pending_application_commands:
        try:
            payload = cmd.to_dict()
        except Exception:
            payload = {"name": getattr(cmd, "name", str(cmd))}
        defs.append(_normalize(payload))
    # 順序の揺れに影響されないようnameでソートしてからJSON化
    defs.sort(key=lambda d: d.get("name", ""))
    raw = json.dumps(defs, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load_synced_hash() -> str | None:
    data = utils.load(_GLOBAL_KEY, "command_sync.json")
    return data.get("hash")


def _save_synced_hash(h: str):
    utils.save(_GLOBAL_KEY, "command_sync.json", {"hash": h})


# ── 同期結果の検証（実際にDiscord側へ反映されたか確認する） ──────────────────────
async def _verify_synced(expected_count: int) -> bool:
    """Discord側に実際に登録されているグローバルコマンド数を取得し、期待値と比較する"""
    try:
        async with aiohttp.ClientSession(
            headers={"Authorization": f"Bot {TOKEN}"}
        ) as session:
            async with session.get(
                "https://discord.com/api/v10/oauth2/applications/@me"
            ) as resp:
                if resp.status != 200:
                    print(f"[verify] application fetch failed: {resp.status}")
                    return False
                app = await resp.json()
                app_id = app["id"]

            async with session.get(
                f"https://discord.com/api/v10/applications/{app_id}/commands"
            ) as resp:
                if resp.status != 200:
                    print(f"[verify] command list fetch failed: {resp.status}")
                    return False
                commands = await resp.json()

        actual_count = len(commands)
        print(f"[verify] actual registered count: {actual_count} (expected {expected_count})", flush=True)
        return actual_count == expected_count
    except Exception as e:
        print(f"[verify] verification failed: {e}")
        return False


# ── イベント ──────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    if not hasattr(bot, "cogs_loaded"):
        for f in os.listdir("./cogs"):
            if f.endswith(".py") and not f.startswith("_"):
                try:
                    bot.load_extension(f"cogs.{f[:-3]}")
                    print(f"cog loaded: {f}")
                except Exception as e:
                    traceback.print_exc()
                    print(f"cog load error: {f} {e}")
        bot.cogs_loaded = True

        cmd_count = len(bot.pending_application_commands)
        print(f"[debug] pending_application_commands count: {cmd_count}", flush=True)
        print(f"[debug] command names: {[c.name for c in bot.pending_application_commands]}", flush=True)

        # コマンドが1件も無いのに同期しようとするのは異常なので、ここで止めてハッシュも保存しない
        if cmd_count == 0:
            print("[警告] pending_application_commandsが0件のため、同期をスキップします。")
            await _notify(RuntimeError(
                "pending_application_commands が0件でした。cogのコマンド定義を確認してください。"
            ))
        else:
            current_hash = _compute_commands_hash()
            previous_hash = None
            force_sync = os.environ.get("FORCE_COMMAND_SYNC") == "1"
            try:
                previous_hash = _load_synced_hash()
            except Exception as e:
                print(f"command hash load failed (will sync anyway): {e}")

            print(f"[debug] current_hash:  {current_hash}", flush=True)
            print(f"[debug] previous_hash: {previous_hash}", flush=True)

            if previous_hash == current_hash and not force_sync:
                print("commands unchanged, skipping sync_commands()")
            else:
                try:
                    await asyncio.wait_for(bot.sync_commands(), timeout=60)
                    print("commands synced")

                    # 実際にDiscord側へ正しく反映されたか検証してからハッシュを保存する
                    if await _verify_synced(cmd_count):
                        _save_synced_hash(current_hash)
                        print("[verify] OK — hash saved")
                    else:
                        print("[verify] NG — Discord側の件数が一致しないため、ハッシュは保存しません")
                        await _notify(RuntimeError(
                            f"sync_commands()は成功と返ったが、Discord側の実際の登録件数が"
                            f"期待値({cmd_count})と一致しませんでした。ハッシュは保存していません。"
                        ))
                except asyncio.TimeoutError:
                    print("command sync timed out after 60s")
                    await _notify(RuntimeError("sync_commands() timed out after 60s"))
                except Exception as e:
                    traceback.print_exc()
                    print(f"command sync error: {e}")
                    await _notify(e)  # 同期失敗を管理者にDMで知らせる

        # 起動/再起動の通知（初回のon_readyでのみ送信、同期の成否に関わらず送る）
        await _notify_startup()

    print(f"ready: {bot.user}")


@bot.event
async def on_application_command_error(ctx, error: Exception):
    await _notify(error, ctx=ctx)
    if ctx and not ctx.response.is_done():
        await ctx.respond("エラーが発生しました。", ephemeral=True)


# ── Webhook通知（Bot本体がハング/不通でも独立して送れる保険ルート） ──────────────
async def _notify_webhook(message: str):
    if not ERROR_WEBHOOK_URL:
        return
    try:
        # 2000文字制限に収める
        content = message[:1900]
        async with aiohttp.ClientSession() as session:
            await session.post(
                ERROR_WEBHOOK_URL,
                json={"content": content},
                timeout=aiohttp.ClientTimeout(total=5),
            )
    except Exception:
        traceback.print_exc()
        print("webhook notify failed")


# ── 起動通知 ──────────────────────────────────────────────────────────────────
async def _notify_startup():
    msg = (
        f"🟢 起動しました\n"
        f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC\n"
        f"user={bot.user}"
    )
    try:
        user = await bot.fetch_user(ADMIN_ID)
        await user.send(msg)
    except Exception:
        traceback.print_exc()
    await _notify_webhook(msg)


# ── エラー通知 ────────────────────────────────────────────────────────────────
async def _notify(error: Exception, ctx=None):
    header = [
        f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC",
        f"{type(error).__name__}: {error}",
    ]
    if ctx:
        header.append(f"guild={ctx.guild} channel={ctx.channel} user={ctx.user}")
    tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    msg = "\n".join(header) + "\n```" + tb[:1500] + "```"
    try:
        user = await bot.fetch_user(ADMIN_ID)
        await user.send(msg)
    except Exception:
        traceback.print_exc()
    await _notify_webhook(msg)


bot.notify = _notify

# ── 起動 ──────────────────────────────────────────────────────────────────────
keep_alive()
bot.run(TOKEN)
