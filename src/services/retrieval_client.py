"""Клиент сервиса поиска/ответов (rag_retrive_docs).

Контракт: POST {retrieval_url}/query
  headers: X-API-Key
  body:    {query: str, mode: "default"|"compliance"|"contradictions"}
  → 200    {answer: str, sources: [{id, text, url, metadata}]}

`metadata` каждого источника содержит s3_key, file_name и (для PDF) doc_items
с bbox — их использует слой предпросмотра для подсветки найденного фрагмента.
"""

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from config import config
from services.http import is_transient

# Пробник живости — короткий запрос. Общий request_timeout (минуты) сюда не
# годится: сайдбар не должен ждать минуту, чтобы показать статус.
_HEALTH_TIMEOUT = 5


class SearchNotReady(RuntimeError):
    """Retrieval-сервис не сконфигурирован (нет URL/ключа в окружении)."""


class SearchError(RuntimeError):
    """Retrieval-сервис вернул ошибку или недоступен."""


def is_configured() -> bool:
    return bool(config.retrieval_url and config.retrieval_api_key)


def health() -> bool:
    """Отвечает ли сервис. /health не требует API-ключа."""
    if not is_configured():
        return False
    try:
        response = httpx.get(f"{config.retrieval_url}/health", timeout=_HEALTH_TIMEOUT)
        return response.is_success
    except httpx.HTTPError:
        return False


@retry(
    retry=retry_if_exception(is_transient),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
def _post(query: str, mode: str) -> dict:
    response = httpx.post(
        f"{config.retrieval_url}/query",
        json={"query": query, "mode": mode},
        headers={"X-API-Key": config.retrieval_api_key},
        timeout=config.request_timeout,
    )
    response.raise_for_status()
    return response.json()


def ask(question: str, mode: str = "default") -> tuple[str, list[dict]]:
    """Возвращает (ответ, документы-источники).

    Вызывается из фонового потока (поиск переживает переключение вкладок),
    поэтому внутри нет никаких st.* — только httpx. Бросает SearchNotReady,
    если сервис не настроен, и SearchError при сбое.
    """
    if not is_configured():
        raise SearchNotReady("Сервис поиска ещё не подключён.")

    try:
        data = _post(question, mode)
        return data.get("answer", ""), data.get("sources", [])
    except httpx.HTTPStatusError as error:
        raise SearchError(
            f"Сервис поиска вернул {error.response.status_code}."
        ) from error
    except httpx.HTTPError as error:
        raise SearchError(f"Сервис поиска недоступен: {error}") from error


def knowledge_graph(
    query: str | None = None,
    node_id: str | None = None,
    offset: int = 0,
    limit: int | None = None,
    chunk_ids: list[str] | None = None,
) -> dict:
    """Подграф знаний: {nodes, edges, total_edges, truncated, limit, offset}.

    query — подстрока имени сущности, node_id — id сущности, чью окрестность
    надо раскрыть (приоритетнее query). И то и другое отрабатывает сервис по
    всей базе, а не фронт по уже загруженной выборке: иначе до связей, не
    попавших в обзор, было бы не добраться.

    chunk_ids — фрагменты документов: показать связи извлечённых из них
    сущностей. Так из ответа в чате переходят к графу.

    offset/limit листают выдачу порциями: размер порции задаёт фронт, потому
    что упирается в него браузер, а не база. Бросает SearchError при сбое.
    """
    if not is_configured():
        raise SearchNotReady("Сервис поиска не подключён")
    params: dict = {
        k: v
        for k, v in (("q", query), ("node", node_id), ("limit", limit), ("chunk", chunk_ids))
        if v
    }
    if offset:
        params["offset"] = offset
    return _get_graph("/graph", params or None)


def graph_node_documents(node_ids: list[str]) -> list[dict]:
    """Документы-источники сущностей: [{file_name, s3_key}].

    Отдельным запросом по действию пользователя, а не вместе с графом: тащить
    источники сразу для всех показанных сущностей — лишняя работа сервиса и
    лишний вес ответа ради данных, которые смотрят у одной-двух.
    """
    if not is_configured():
        raise SearchNotReady("Сервис поиска не подключён")
    if not node_ids:
        return []
    return _get_graph("/graph/documents", {"node": node_ids}).get("docs", [])


def _get_graph(path: str, params: dict | None) -> dict:
    try:
        response = httpx.get(
            f"{config.retrieval_url}{path}",
            params=params,
            headers={"X-API-Key": config.retrieval_api_key},
            timeout=60,  # обход Neo4j дольше поллинга статусов
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as error:
        raise SearchError(f"Не удалось получить граф знаний: {error}") from error
