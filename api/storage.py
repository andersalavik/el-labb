import json
import re
import time
import uuid
from pathlib import Path

from flask import current_app


def _get_saves_dir():
    saves_dir = Path(current_app.root_path) / "saves"
    saves_dir.mkdir(parents=True, exist_ok=True)
    return saves_dir


def _load_save(path):
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def safe_name(name):
    return re.sub(r"[^a-zA-Z0-9 _-]", "", name).strip()


def list_saves():
    saves = []
    saves_dir = _get_saves_dir()
    for path in saves_dir.glob("*.json"):
        data = _load_save(path)
        if not data:
            continue
        saves.append(
            {
                "id": data.get("id", path.stem),
                "name": data.get("name", path.stem),
                "updatedAt": data.get("updatedAt", 0),
            }
        )
    return sorted(saves, key=lambda item: item["updatedAt"], reverse=True)


def load_snapshot(save_id):
    path = _get_saves_dir() / f"{save_id}.json"
    data = _load_save(path)
    if not data:
        return None
    return data.get("snapshot", {})


def delete_save(save_id):
    path = _get_saves_dir() / f"{save_id}.json"
    if not path.exists():
        return False
    try:
        path.unlink()
    except OSError:
        return None
    return True


def save_snapshot(name, snapshot, save_id=None):
    saves_dir = _get_saves_dir()
    existing = None
    if save_id:
        path = saves_dir / f"{save_id}.json"
        existing = _load_save(path) if path.exists() else None
    else:
        for path in saves_dir.glob("*.json"):
            data = _load_save(path)
            if data and data.get("name") == name:
                existing = data
                save_id = data.get("id", path.stem)
                break

    if not save_id:
        save_id = str(uuid.uuid4())

    timestamp = int(time.time() * 1000)
    record = {
        "id": save_id,
        "name": name,
        "snapshot": snapshot,
        "updatedAt": timestamp,
    }
    if existing and "createdAt" in existing:
        record["createdAt"] = existing["createdAt"]
    else:
        record["createdAt"] = record["updatedAt"]

    path = saves_dir / f"{save_id}.json"
    with path.open("w", encoding="utf-8") as handle:
        json.dump(record, handle, ensure_ascii=True, indent=2)

    return record
