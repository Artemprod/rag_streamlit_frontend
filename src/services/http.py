"""Что имеет смысл повторять при обращении к сервисам.

Повтор лечит обрыв связи и 5xx. На 401/404/422 он бесполезен: ответ не
изменится, а пользователь ждёт ошибку лишние секунды экспоненциальной паузы.
"""

import httpx

_SERVER_ERROR = 500


def is_transient(error: BaseException) -> bool:
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code >= _SERVER_ERROR
    return isinstance(error, httpx.HTTPError)  # таймауты, обрывы, DNS
