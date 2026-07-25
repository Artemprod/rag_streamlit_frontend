"""Клиент сервиса обработки (rag_save_pipline).

Контракт:
  POST {process_url}/pipeline/process
    headers: X-API-Key
    body:    {s3_keys: [...], domain_context: str|None, dataset: str}
    → 202    {status: "accepted", job_id: str, files: int}

  GET {process_url}/pipeline/status/{job_id}
    → 200    {job_id, dataset, status, total_files, files_loaded, files_failed,
              nodes_total, nodes_translated, nodes_persisted, nodes_graphed,
              nodes_failed, progress: 0..1, error: str|None}
    → 404    задача не найдена

  GET {process_url}/pipeline/jobs/{job_id}/dead-letters
    → 200    [{stage, items, error}]

Сервис принимает работу асинхронно, но НЕ безответно: он сразу отдаёт job_id,
по которому прогресс отслеживается поллингом /status/{job_id} до терминального
статуса.
"""

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from config import config

# Статусы, после которых задача больше не меняется — поллинг прекращаем.
# Зеркалит JobStatus сервиса обработки; дублирование этого контракта дешевле
# общего модуля, связывающего два репозитория.
TERMINAL_STATUSES = frozenset({"completed", "completed_with_errors", "failed"})

# Поллинг статуса — короткий запрос. Общий request_timeout (минуты) сюда не
# годится: залипший вызов заморозил бы обновление прогресса в UI.
_POLL_TIMEOUT = 10


class ProcessError(RuntimeError):
    """Не удалось поставить документы в обработку."""


def is_terminal(status_value: str) -> bool:
    return status_value in TERMINAL_STATUSES


def _headers() -> dict[str, str]:
    return {"X-API-Key": config.process_api_key}


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
def _post(payload: dict) -> dict:
    """Постановку ретраим: терять задачу нельзя. Сервис дедуплицирует повторы
    по содержимому запроса, поэтому ретрай не создаёт задачу-дубль."""
    response = httpx.post(
        f"{config.process_url}/pipeline/process",
        json=payload,
        headers=_headers(),
        timeout=config.request_timeout,
    )
    response.raise_for_status()
    return response.json()


def _get(path: str):
    """Чтение без ретраев: поллинг всё равно повторит запрос через секунды,
    а exponential backoff заморозил бы фрагмент UI на десяток секунд."""
    response = httpx.get(
        f"{config.process_url}{path}", headers=_headers(), timeout=_POLL_TIMEOUT
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


def status(job_id: str) -> dict | None:
    """Снимок прогресса задачи.

    None — если задача сервису неизвестна (404) или он временно недоступен:
    вызывающий сохраняет последнее известное состояние, а не показывает ошибку
    из-за одного неудачного опроса.
    """
    try:
        return _get(f"/pipeline/status/{job_id}")
    except httpx.HTTPError:
        return None


def dead_letters(job_id: str) -> list[dict]:
    """Батчи, потерянные после всех ретраев: что и почему не доехало."""
    try:
        return _get(f"/pipeline/jobs/{job_id}/dead-letters") or []
    except httpx.HTTPError as error:
        raise ProcessError(f"Не удалось получить список потерь: {error}") from error
