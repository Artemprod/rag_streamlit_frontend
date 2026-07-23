FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Streamlit не запускается из корня ФС — рабочий каталог обязателен
WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/usr/local PYTHONUNBUFFERED=1

# Зависимости отдельным слоем — кэшируются между сборками
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY .streamlit ./.streamlit
COPY src ./src

ENTRYPOINT ["streamlit", "run", "src/app.py", \
            "--server.address=0.0.0.0", \
            "--server.headless=true", \
            "--server.maxUploadSize=500"]