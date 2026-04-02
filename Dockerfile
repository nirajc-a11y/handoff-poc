FROM python:3.13-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY . .

RUN alembic upgrade head 2>/dev/null || true

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
