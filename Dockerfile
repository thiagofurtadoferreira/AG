# Node 24 is used by yt-dlp-ejs to extract YouTube formats.
FROM node:24-bookworm-slim AS js-runtime
FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=js-runtime /usr/local/bin/node /usr/local/bin/node
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && node --version && python -m yt_dlp --version
COPY app.py .
RUN useradd -m -u 10001 reeldrop
USER reeldrop
EXPOSE 8000
CMD ["sh","-c","exec uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}"]
