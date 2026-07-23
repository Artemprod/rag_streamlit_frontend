"""Единая типобезопасная конфигурация фронта.

Все секреты и адреса сервисов приходят из окружения (.env). Ничего не
хардкодим в коде — см. .env.example для полного списка переменных.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# .env ищем в корне проекта (на уровень выше src/), а не относительно CWD —
# иначе запуск из другой директории терял конфиг. Переменные окружения читаются
# в любом случае, даже если файла нет (актуально для Docker/compose).
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), extra="ignore")

    # ── S3 / MinIO (исходные документы) ───────────────────────────────
    s3_endpoint_url: str
    s3_access_key: str
    s3_secret_key: str
    s3_bucket: str = "documents"
    s3_region: str | None = None

    # ── Сервис обработки (rag_save_pipline) ───────────────────────────
    process_url: str = "http://process:8000/api"
    process_api_key: str

    # ── Сервис поиска/ответов (rag_retrive_docs) ──────────────────────
    # Пусто → чат покажет дружелюбное «сервис не подключён» вместо падения.
    retrieval_url: str | None = None
    retrieval_api_key: str | None = None

    request_timeout: int = 300

    # ── Аутентификация (single admin + cookie-сессия) ─────────────────
    admin_username: str = "admin"
    admin_name: str = "Администратор"
    admin_password: str
    # Секрет для подписи cookie сессии. В проде задать длинным случайным.
    auth_cookie_key: str = "change-me-in-prod"
    auth_cookie_name: str = "rag_ui_auth"
    auth_cookie_expiry_days: float = 7.0


config = Config()
