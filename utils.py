import json, os, subprocess
from pathlib import Path

_BASE    = Path(__file__).parent
DATA_DIR = _BASE / "data" / "guilds"

def _mkdir(p: Path):
    if p.exists():
        return
    subprocess.run(
        ["cmd", "/c", "mkdir", str(p)],
        check=False,  # 既存・失敗どちらも無視
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

_mkdir(DATA_DIR)

def guild_path(guild_id, filename):
    return DATA_DIR / str(guild_id) / filename

def load(guild_id, filename):
    p = guild_path(guild_id, filename)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))

def save(guild_id, filename, data):
    p = guild_path(guild_id, filename)
    _mkdir(p.parent)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def get_config(guild_id):
    return load(guild_id, "config.json")
