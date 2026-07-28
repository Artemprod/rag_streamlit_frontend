"""История диалогов чата: JSON-файл на диске.

Приложение single-admin, поэтому никакой БД: один файл, атомарная запись
через временный файл. Путь по умолчанию /data — в compose примонтирован
томом, история переживает пересборку контейнера. Если каталог недоступен,
функции тихо деградируют: чат работает, истории просто нет.
"""

import json
import os
import uuid
from datetime import datetime
from pathlib import Path

from loguru import logger

_STORE = Path(os.getenv("CHAT_HISTORY_FILE", "/data/chats.json"))
MAX_CHATS = 30


def _read() -> list[dict]:
    try:
        return json.loads(_STORE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _write(chats: list[dict]) -> None:
    try:
        _STORE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _STORE.with_suffix(".tmp")
        tmp.write_text(json.dumps(chats, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_STORE)
    except OSError as error:  # нет тома/прав — работаем без истории
        logger.warning(f"История диалогов недоступна: {error}")


def save(chat_id: str | None, messages: list[dict]) -> str | None:
    """Создаёт или обновляет диалог. Возвращает его id (None — нечего хранить)."""
    if not messages:
        return chat_id
    chats = _read()
    title = next(
        (m["content"][:80] for m in messages if m["role"] == "user"), "Диалог"
    )
    record = {
        "id": chat_id or str(uuid.uuid4()),
        "title": title,
        "updated_at": datetime.now().strftime("%d.%m %H:%M"),
        "messages": messages,
    }
    chats = [c for c in chats if c["id"] != record["id"]]
    chats.insert(0, record)
    _write(chats[:MAX_CHATS])
    return record["id"]


def summaries() -> list[dict]:
    """[{id, title, updated_at}] от свежих к старым."""
    return [
        {"id": c["id"], "title": c["title"], "updated_at": c["updated_at"]}
        for c in _read()
    ]


def get(chat_id: str) -> list[dict]:
    return next((c["messages"] for c in _read() if c["id"] == chat_id), [])
