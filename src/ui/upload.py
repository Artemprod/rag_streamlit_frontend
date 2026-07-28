"""Страница «Загрузка» — заливка документов и постановка на обработку.

Поток: выбор файлов → фоновая заливка в S3 → постановка в обработку пачками по
мере готовности (первые документы обрабатываются, пока остальные ещё грузятся)
→ поллинг прогресса задач до терминального статуса.

Прогресс показываем честно на всех стадиях: сервис обработки отдаёт снимок
счётчиков (файлы загружены/упали, ноды переведены/записаны/попали в граф),
поэтому пользователь видит движение конвейера, а не только факт приёма.
"""

from datetime import datetime

import streamlit as st

from services import process_client
from services import s3 as s3_service
from services.process_client import ProcessError

# Отображение статусов. Ключи — статусы сервиса обработки плюс локальный
# upload_failed (до сервиса дело не дошло).
_STATUS_VIEW = {
    "queued": ("📨", "В очереди"),
    "running": ("⚙️", "Обрабатывается"),
    "completed": ("✅", "Готово"),
    "completed_with_errors": ("⚠️", "Готово, часть данных потеряна"),
    "failed": ("❌", "Ошибка обработки"),
    "upload_failed": ("❌", "Не удалось отправить"),
}

# Счётчики стадий из снимка статуса — берём подмножеством, чтобы запись задачи
# не тащила служебные поля ответа.
_COUNTERS = (
    "total_files",
    "files_loaded",
    "files_failed",
    "nodes_total",
    "nodes_translated",
    "nodes_persisted",
    "nodes_graphed",
    "nodes_failed",
)

# Сколько имён файлов показывать, прежде чем свернуть в «…и ещё N».
_MAX_NAMES_SHOWN = 20
_POLL_INTERVAL = "2s"

# Сколько залившихся файлов копим, прежде чем ставить их одной задачей.
# Без накопления каждый тик отправлял бы то, что успело залиться за секунду —
# и сотня документов превращалась бы в сотню задач в очереди.
_DISPATCH_BATCH = 10

# Сколько задач опрашиваем за тик — потолок нагрузки на сервис независимо от
# числа документов (см. _render_active_jobs).
_POLL_WINDOW = 5

# Пояснения на языке пользователя: что произойдёт с файлами и зачем нужны поля.
# Держим их здесь, а не в вызовах виджетов, чтобы текст было легко править.
_ABOUT_TEXT = """
**Что произойдёт с файлами**

1. Файлы сохранятся в хранилище — оригиналы никуда не денутся, их можно
   открыть из ответа в чате.
2. Мы прочитаем текст, в том числе со сканов и фотографий страниц
   (распознавание), и переведём его на русский, если документ на другом языке.
3. Текст разобьётся на небольшие фрагменты, по которым потом ищется ответ.

**Что это даёт**

В чате можно спросить обычными словами — «какие обязанности у отдела закупок?»
— и получить ответ со ссылкой на конкретный документ и место в нём.
Без загрузки чат отвечать не по чему.

**Сколько ждать**

Страница со сканом распознаётся примерно минуту. Можно закрыть вкладку:
обработка идёт на сервере, прогресс появится здесь же, когда вернётесь.

**Когда загружать не нужно**

Если документ уже загружали — повторная загрузка не нужна, файл просто
перезапишется. Картинки без текста и защищённые паролем файлы обработать
не получится.
"""

_DATASET_HELP = (
    "Папка, в которую сложатся документы. В чате можно искать по одному "
    "набору и не мешать его с остальными — например, «кадры» и «закупки» "
    "отдельно. Если не уверены, оставьте как есть."
)

_DOMAIN_HELP = (
    "Пара слов о том, чему посвящены документы: «банковские регламенты», "
    "«строительные нормы». Помогает правильно перевести термины и сокращения. "
    "Можно не заполнять."
)

_UPLOADER_HELP = (
    "PDF, DOCX, PPTX, XLSX/XLS, CSV, MD, TXT. Сканы и фотографии страниц "
    "внутри PDF тоже подойдут — текст с них распознается."
)


def _record_job(*, dataset: str, file_names: list[str], status: str, **extra) -> None:
    """Заводит запись о пакете. В extra — необязательные поля записи:

    job_id, error, а для неудавшейся постановки ещё s3_keys и domain_context:
    файлы уже залиты, и повтор не должен гнать их через хранилище заново.
    """
    st.session_state.jobs.insert(
        0,
        {
            "job_id": None,
            "created_at": datetime.now().strftime("%H:%M:%S"),
            "dataset": dataset,
            "file_names": file_names,
            "files": len(file_names),
            "status": status,
            "progress": 0.0,
            "stats": None,
            "error": None,
            "s3_keys": None,
            "domain_context": None,
            **extra,
        },
    )


def _render_uploader() -> None:
    # Основной сценарий — просто перетащить файлы. Папка вынесена вторично.
    files = st.file_uploader(
        "Перетащите файлы сюда или выберите",
        accept_multiple_files=True,
        width="stretch",
        help=_UPLOADER_HELP,
        key=f"file_uploader_{st.session_state.uploader_key}",
    )
    with st.expander("📁 …или загрузить папку целиком"):
        folder = st.file_uploader(
            "Папка",
            accept_multiple_files="directory",
            width="stretch",
            label_visibility="collapsed",
            key=f"folder_uploader_{st.session_state.uploader_key}",
        )

    uploaded = (files or []) + (folder or [])
    if uploaded:
        st.success(f"Выбрано файлов: **{len(uploaded)}**")

    # Настройки и кнопка видны всегда — понятно, что будет дальше. Кнопка
    # неактивна, пока не выбраны файлы или пока идёт заливка.
    col_ds, col_ctx = st.columns(2)
    dataset = col_ds.text_input("Набор документов", value="yello", help=_DATASET_HELP)
    domain_context = (
        col_ctx.text_area("О чём документы (необязательно)", help=_DOMAIN_HELP) or None
    )

    busy = st.session_state.upload_futures is not None
    if st.button(
        "🚀 Сохранить и обработать",
        width="stretch",
        type="primary",
        disabled=busy or not uploaded,
    ):
        uploads = s3_service.upload_async(uploaded)
        st.session_state.upload_futures = uploads
        st.session_state.upload_meta = {
            "dataset": dataset,
            "domain_context": domain_context,
            "total": len(uploads),
        }
        st.session_state.uploader_key += 1
        st.rerun()


def _dispatch(ready: list, dataset: str, domain_context: str | None) -> None:
    """Отправляет группу залившихся файлов в обработку одной задачей.

    Упавшие заливки фиксируются отдельной записью-ошибкой; сбой постановки
    не трогает остальные группы — их отправят следующие тики.
    """
    ok = [(name, f.result()) for name, f in ready if f.exception() is None]
    lost = [(name, f.exception()) for name, f in ready if f.exception() is not None]

    if lost:
        _record_job(
            dataset=dataset,
            file_names=[name for name, _ in lost],
            status="upload_failed",
            error=str(lost[0][1]),
        )
        st.toast(f"Не залилось файлов: {len(lost)}", icon="❌")
    if not ok:
        return

    try:
        result = process_client.process([key for _, key in ok], dataset, domain_context)
        _record_job(
            dataset=dataset,
            file_names=[name for name, _ in ok],
            status="queued",
            job_id=result.get("job_id"),
        )
    except ProcessError as error:
        _record_job(
            dataset=dataset,
            file_names=[name for name, _ in ok],
            status="upload_failed",
            error=str(error),
            s3_keys=[key for _, key in ok],
            domain_context=domain_context,
        )
        st.toast(f"Не удалось поставить на обработку: {error}", icon="❌")


@st.fragment(run_every="1s")
def _render_upload_progress() -> None:
    """Каждую секунду: залившиеся файлы копим и ставим пачками по десять.

    Первые документы начинают обрабатываться, пока хвост ещё грузится в S3,
    но задач в очереди получается в десять раз меньше, чем файлов.
    Перерисовывается только этот фрагмент, остальная страница не трогается.
    """
    uploads = st.session_state.upload_futures
    if not uploads:
        return

    meta = st.session_state.upload_meta or {}
    ready = st.session_state.upload_ready + [(n, f) for n, f in uploads if f.done()]
    pending = [(name, f) for name, f in uploads if not f.done()]
    st.session_state.upload_futures = pending or None

    # Хвост отправляем не дожидаясь полной пачки — иначе последние файлы
    # застряли бы в буфере навсегда.
    dispatched = bool(ready) and (len(ready) >= _DISPATCH_BATCH or not pending)
    if dispatched:
        _dispatch(ready, meta.get("dataset", "yello"), meta.get("domain_context"))
        ready = []
    st.session_state.upload_ready = ready

    if pending:
        total = meta.get("total", len(pending)) or 1
        st.progress(
            1 - len(pending) / total,
            text=f"Загрузка в хранилище: {total - len(pending)}/{total}",
        )
        if dispatched:
            # Часть уже ушла в обработку — показываем её в разделе «В работе».
            st.rerun(scope="app")
    else:
        st.session_state.upload_meta = None
        st.rerun(scope="app")


def _apply_snapshot(job: dict, snapshot: dict) -> None:
    """Переносит снимок статуса сервиса в запись задачи (мутирует на месте)."""
    job["status"] = snapshot.get("status", job["status"])
    job["progress"] = snapshot.get("progress", job.get("progress") or 0.0)
    job["error"] = snapshot.get("error") or job.get("error")
    # Позиция в очереди сервиса: пока задача ждёт, это единственное, что
    # вообще движется, — по ней видно, что очередь разбирается.
    job["queue_position"] = snapshot.get("queue_position")
    job["stats"] = {name: snapshot.get(name, 0) for name in _COUNTERS}


def _stats_line(stats: dict) -> str:
    """Одна строка про стадии конвейера: файлы, затем ноды по этапам."""
    parts = [f"файлы {stats['files_loaded']}/{stats['total_files']}"]
    if stats["nodes_total"]:
        parts += [
            f"перевод {stats['nodes_translated']}/{stats['nodes_total']}",
            f"запись {stats['nodes_persisted']}/{stats['nodes_total']}",
            f"граф {stats['nodes_graphed']}/{stats['nodes_total']}",
        ]
    lost = stats["files_failed"] + stats["nodes_failed"]
    if lost:
        parts.append(f"потеряно {lost}")
    return " · ".join(parts)


def _active_jobs() -> list[dict]:
    """Задачи, за которыми ещё имеет смысл следить."""
    return [
        job
        for job in st.session_state.jobs
        if job.get("job_id") and not process_client.is_terminal(job["status"])
    ]


def _total_stats(jobs: list[dict]) -> dict | None:
    """Счётчики стадий, просуммированные по задачам (None — снимков ещё нет)."""
    snapshots = [job["stats"] for job in jobs if job.get("stats")]
    if not snapshots:
        return None
    return {
        name: sum(snapshot.get(name, 0) for snapshot in snapshots) for name in _COUNTERS
    }


def _ahead_line(queued: list[dict]) -> str:
    """Сколько чужих задач стоит перед нашей очередью.

    Сервис берёт задачи по одной и по порядку, поэтому пока перед нами есть
    хвост прошлых загрузок, проценты стоят на нуле — и это не поломка. Число
    впереди уменьшается на глазах, по нему видно, что очередь разбирается.
    """
    positions = [job["queue_position"] for job in queued if job.get("queue_position")]
    if not positions:
        return ""
    ahead = min(positions) - 1
    return f"впереди задач: {ahead}" if ahead > 0 else "следующая на очереди"


@st.fragment(run_every=_POLL_INTERVAL)
def _render_active_jobs() -> None:
    """Поллит незавершённые задачи и рисует ОДИН общий прогресс на всё.

    Сто документов — это десяток задач в очереди сервиса, но для пользователя
    это одна операция: важно, сколько всего файлов в работе и сколько ещё
    ждёт. Поэтому вместо полосы на задачу — одна полоса и одна строка со
    сводкой по стадиям.

    Неудачный опрос не считается ошибкой задачи: сохраняем последнее известное
    состояние и пробуем снова на следующем тике. Когда задача дошла до
    терминального статуса — просим полный ререн, чтобы она переехала в историю
    и фрагмент перестал тикать.
    """
    active = _active_jobs()
    if not active:
        return

    # Поллим только самые старые задачи. Сервис берёт их из очереди по одной
    # и по порядку, поэтому меняться может лишь голова очереди: остальные
    # честно стоят «в очереди», и спрашивать про них нечего. Без этого тысяча
    # документов (сотня задач) давала бы полсотни запросов в секунду.
    # jobs хранится новыми вперёд, значит голова очереди — в хвосте списка.
    for job in active[-_POLL_WINDOW:]:
        snapshot = process_client.status(job["job_id"])
        if snapshot is not None:
            _apply_snapshot(job, snapshot)

    running = [job for job in active if job["status"] == "running"]
    queued = [job for job in active if job["status"] == "queued"]
    files = sum(job["files"] for job in active)
    # Прогресс взвешиваем по числу файлов: задача на 10 документов не должна
    # весить столько же, сколько задача на один.
    done = sum((job.get("progress") or 0.0) * job["files"] for job in active)

    parts = []
    if running:
        parts.append(f"⚙️ обрабатывается {sum(job['files'] for job in running)}")
    if queued:
        parts.append(f"📨 в очереди +{sum(job['files'] for job in queued)}")
    parts.append(f"всего {files} документов")

    st.subheader("В работе")
    st.progress(done / files if files else 0.0, text=" · ".join(parts))

    # Пока всё стоит в очереди, проценты честно равны нулю — и полоса выглядит
    # зависшей. Показываем то, что на самом деле движется: место в очереди
    # сервиса и время последнего ответа. Иначе пользователь видит «ничего не
    # происходит» там, где идёт разбор чужих задач.
    details = [_ahead_line(queued)]
    stats = _total_stats(running)
    if stats:
        details.append(_stats_line(stats))
    details.append(f"обновлено {datetime.now().strftime('%H:%M:%S')}")
    st.caption(" · ".join(part for part in details if part))

    if any(process_client.is_terminal(job["status"]) for job in active):
        st.rerun(scope="app")


def _render_dead_letters(job_id: str, key: str) -> None:
    """Детали потерь тянем по кнопке: незачем дёргать сервис на каждый рендер."""
    if not st.button("Показать потерянные батчи", key=f"dl_{key}"):
        return
    try:
        rows = process_client.dead_letters(job_id)
    except ProcessError as error:
        st.warning(str(error))
        return
    if not rows:
        st.caption("Сервис не сохранил детали потерь.")
        return
    for row in rows:
        st.markdown(f"**Стадия {row.get('stage', '?')}** — {row.get('error', '')}")
        items = row.get("items") or []
        if items:
            st.caption(", ".join(items[:_MAX_NAMES_SHOWN]))


def _render_retry(job: dict, key: str) -> None:
    """Повторная постановка уже залитых файлов — без новой заливки в S3.

    Сервис обработки может быть недоступен в момент отправки (перезапуск,
    падение сети). Файлы при этом уже лежат в хранилище, и гнать их туда
    заново вредно вдвойне: долго и лишний повод для конфликта на бакете.
    Поэтому повторяем только постановку, по сохранённым ключам.
    """
    if not job.get("s3_keys") or not st.button(
        "🔁 Повторить отправку", key=f"retry_{key}"
    ):
        return
    try:
        result = process_client.process(
            job["s3_keys"], job["dataset"], job.get("domain_context")
        )
    except ProcessError as error:
        st.warning(f"Сервис всё ещё недоступен: {error}")
        return
    job.update(job_id=result.get("job_id"), status="queued", error=None)
    st.rerun()


def _render_history() -> None:
    st.subheader("История обработки")
    jobs = [
        job
        for job in st.session_state.jobs
        if not job.get("job_id") or process_client.is_terminal(job["status"])
    ]
    if not jobs:
        st.caption("Пока ничего не завершено.")
        return

    for idx, job in enumerate(jobs):
        icon, label = _STATUS_VIEW.get(job["status"], ("•", job["status"]))
        with st.expander(
            f"{icon} {job['created_at']} — {job['files']} файл(ов) · {label}",
            expanded=False,
        ):
            st.write(f"**Датасет:** {job['dataset']}")
            st.write("**Файлы:** " + ", ".join(job["file_names"][:_MAX_NAMES_SHOWN]))
            if len(job["file_names"]) > _MAX_NAMES_SHOWN:
                st.caption(f"…и ещё {len(job['file_names']) - _MAX_NAMES_SHOWN}")
            if job.get("stats"):
                st.caption(_stats_line(job["stats"]))
            if job.get("error"):
                st.error(job["error"])
            if job["status"] == "completed_with_errors" and job.get("job_id"):
                _render_dead_letters(job["job_id"], f"{idx}_{job['job_id']}")
            if job["status"] == "upload_failed":
                # Ключ по времени создания, а не по индексу: записи переезжают
                # между «в работе» и историей, индекс не стабилен.
                _render_retry(job, f"{job['created_at']}_{idx}")


def render() -> None:
    st.markdown("## 📤 Загрузка документов")
    st.caption(
        "Добавьте файлы или папку — они уйдут на обработку и станут доступны "
        "для вопросов в чате. Поддерживаются PDF, DOCX, PPTX, XLSX/XLS, "
        "CSV, MD, TXT."
    )
    # Всплывашка, а не всегда развёрнутый текст: тем, кто уже разобрался,
    # объяснение не мешает, а новому пользователю доступно в один клик.
    with st.popover("❓ Зачем это нужно и что будет с файлами"):
        st.markdown(_ABOUT_TEXT)
    _render_uploader()

    # Фрагменты с run_every вызываем только когда есть что поллить, иначе они
    # тикали бы вечно и дёргали сервис на пустом месте.
    if st.session_state.upload_futures:
        _render_upload_progress()

    st.divider()
    if _active_jobs():
        _render_active_jobs()
    _render_history()
