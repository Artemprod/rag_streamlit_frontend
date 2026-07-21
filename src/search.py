class SearchNotReady(RuntimeError):
    """Ретрив вынесен в отдельный сервис, пока не подключён."""


def ask(question: str) -> tuple[str, list]:
    raise SearchNotReady("Сервис поиска ещё не подключён")