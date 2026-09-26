FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.8.22 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY backend ./backend
COPY extension ./extension
RUN useradd --uid 10001 --create-home agent && mkdir data && chown agent:agent data
USER agent
EXPOSE 8000
CMD [".venv/bin/uvicorn", "app.main:create_app", "--factory", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
