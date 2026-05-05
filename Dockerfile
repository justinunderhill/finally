FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV FINALLY_DB_PATH=/app/db/finally.db

WORKDIR /app/backend

RUN pip install --no-cache-dir uv

COPY backend/ ./

RUN uv sync --frozen --no-dev

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
