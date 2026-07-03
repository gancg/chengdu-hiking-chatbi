FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    CHATBI_HOST=0.0.0.0 \
    CHATBI_PORT=8000 \
    CHATBI_WEB_HOST=0.0.0.0 \
    CHATBI_WEB_PORT=7860 \
    CHATBI_DB_PATH=/app/runtime/chatbi.db

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt \
    && playwright install --with-deps chromium \
    && chmod -R a+rX /ms-playwright

COPY hiking_chatbi ./hiking_chatbi
COPY qwen_agent ./qwen_agent
COPY data ./data
COPY .env.example ./

RUN mkdir -p /app/runtime

EXPOSE 8000 7860
VOLUME ["/app/runtime"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()"]

CMD ["python", "-m", "hiking_chatbi", "app"]
