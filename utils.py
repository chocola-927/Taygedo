import os
from pymongo import MongoClient

_client = MongoClient(os.environ["MONGO_URI"])
_db     = _client["taygedo"]

try:
    _client.admin.command("ping")
    print("MongoDB connected")
except Exception as e:
    print(f"MongoDB connection failed: {e}")


def _col(guild_id: str, filename: str):
    """guilds/{guild_id}/{filename} に対応するコレクションを返す"""
    name = filename.replace(".json", "")
    return _db[f"{guild_id}_{name}"]


def load(guild_id: str, filename: str) -> dict:
    col = _col(guild_id, filename)
    doc = col.find_one({"_id": "data"})
    if not doc:
        return {}
    data = dict(doc)
    data.pop("_id", None)
    return data


def save(guild_id: str, filename: str, data: dict):
    col = _col(guild_id, filename)
    col.replace_one({"_id": "data"}, {"_id": "data", **data}, upsert=True)


def get_config(guild_id: str) -> dict:
    return load(guild_id, "config.json")
