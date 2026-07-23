"""Клиент сервиса обработки (rag_save_pipline).

Контракт: POST {process_url}/pipeline/process
  headers: X-API-Key
  body:    {s3_keys: [...], domain_context: str|None, dataset: str}
  → 202    {status: "accepted", files: int}

Сервис принимает работу асинхронно (fire-and-forget), поэтому job-id и статуса
обработки он не возвращает — ответ подтверждает только приём в очередь.
"""

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from config import config


class ProcessError(RuntimeError):
    """Не удалось поставить документы в обработку."""


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
def _post(payload: dict) -> dict:
    response = httpx.post(
        f"{config.process_url}/pipeline/process",
        json=payload,
        headers={"X-API-Key": config.process_api_key},
        timeout=config.request_timeout,
    )
    response.raise_for_status()
    return response.json()


def process(
    s3_keys: list[str], dataset: str, domain_context: str | None = None
) -> dict:
    """Ставит пакет ключей на обработку. Бросает ProcessError при сбое."""
    try:
        return _post(
            {"s3_keys": s3_keys, "domain_context": domain_context, "dataset": dataset}
        )
    except httpx.HTTPStatusError as error:
        raise ProcessError(
            f"Сервис обработки вернул {error.response.status_code}"
        ) from error
    except httpx.HTTPError as error:
        raise ProcessError(f"Сервис обработки недоступен: {error}") from error
