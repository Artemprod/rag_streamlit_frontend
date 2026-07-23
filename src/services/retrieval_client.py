"""Клиент сервиса поиска/ответов (rag_retrive_docs).

Контракт: POST {retrieval_url}/query
  headers: X-API-Key
  body:    {query: str}
  → 200    {answer: str, sources: [{id, text, url, metadata}]}

`metadata` каждого источника содержит s3_key, file_name и (для PDF) doc_items
с bbox — их использует слой предпросмотра для подсветки найденного фрагмента.
"""

import httpx
import streamlit as st
from tenacity import retry, stop_after_attempt, wait_exponential

from config import config


class SearchNotReady(RuntimeError):
    """Retrieval-сервис не сконфигурирован (нет URL/ключа в окружении)."""


class SearchError(RuntimeError):
    """Retrieval-сервис вернул ошибку или недоступен."""


def is_configured() -> bool:
    return bool(config.retrieval_url and config.retrieval_api_key)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
def _post(query: str) -> dict:
    response = httpx.post(
        f"{config.retrieval_url}/query",
        json={"query": query},
        headers={"X-API-Key": config.retrieval_api_key},
        timeout=config.request_timeout,
    )
    response.raise_for_status()
    return response.json()


# Кэшируем по тексту вопроса: повторный вопрос не гоняет LLM-агента заново,
# а reruns (клик по источнику и т.п.) вообще не приводят к сетевым вызовам.
@st.cache_data(show_spinner=False, max_entries=64, ttl=3600)
def _ask_cached(query: str) -> tuple[str, list[dict]]:
    data = _post(query)
    return data.get("answer", ""), data.get("sources", [])


def ask(question: str) -> tuple[str, list[dict]]:
    """Возвращает (ответ, документы-источники).

    Бросает SearchNotReady, если сервис не настроен, и SearchError при сбое.
    """
    if not is_configured():
        raise SearchNotReady("Сервис поиска ещё не подключён.")

    try:
        return _ask_cached(question)
    except httpx.HTTPStatusError as error:
        raise SearchError(
            f"Сервис поиска вернул {error.response.status_code}."
        ) from error
    except httpx.HTTPError as error:
        raise SearchError(f"Сервис поиска недоступен: {error}") from error
