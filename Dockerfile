# スマホだけで使うための常時公開用（Render / Railway / Fly.io）
FROM python:3.12-slim-bookworm
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py ./
COPY templates ./templates
COPY static ./static
COPY sandbox ./sandbox
RUN mkdir -p /app/sandbox/data

ENV PYTHONUNBUFFERED=1
ENV VOICE_CLOUD=1
EXPOSE 8080

# 既定は Flask（アプリ起動.bat と同じ画面）。
# 以前の Idea City / Notebook を載せるときだけ APP=voice
CMD ["sh", "-c", "if [ \"$APP\" = \"voice\" ]; then uvicorn sandbox.app.voice_server:app --host 0.0.0.0 --port ${PORT:-8080}; else gunicorn app:app --bind 0.0.0.0:${PORT:-8080} --workers 1 --threads 4 --timeout 120; fi"]
