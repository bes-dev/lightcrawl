FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir ".[mcp]"

COPY src/ src/

ENV PYTHONUNBUFFERED=1

EXPOSE 3002

CMD ["sh", "-c", "uvicorn src.main:app --host 0.0.0.0 --port 3002 --workers ${API_WORKERS:-4}"]
