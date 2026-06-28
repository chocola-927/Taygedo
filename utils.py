import json, os
from pathlib import Path
 
_BASE    = Path(__file__).parent
DATA_DIR = _BASE / "data" / "guilds"
 
def guild_path(guild_id, filename):
    return DATA_DIR / str(guild_id) / filename
 
def load(guild_id, filename):
    path = guild_path(guild_id, filename)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))
 
def save(guild_id, filename, data):
    path = guild_path(guild_id, filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
 
def get_config(guild_id):
    return load(guild_id, "config.json")
