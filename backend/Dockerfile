FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh \
    && groupadd --gid 1000 resonar \
    && useradd --uid 1000 --gid 1000 --no-create-home --home-dir /tmp resonar

# UID 1000 matches the host owner of the ./data, ./media and ./config bind
# mounts. Temp files (yt-dlp downloads, batch zips in progress) go to
# /data/tmp on disk rather than a RAM tmpfs: a 100-track batch is ~0.5 GB.
ENV HOME=/tmp \
    XDG_CACHE_HOME=/tmp/.cache \
    TMPDIR=/data/tmp
USER resonar

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/health').status==200 else 1)"

CMD ["./entrypoint.sh"]
