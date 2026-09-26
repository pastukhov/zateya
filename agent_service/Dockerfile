# syntax=docker/dockerfile:1
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git openssh-client \
    && rm -rf /var/lib/apt/lists/*
COPY agent_service/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && python -c 'import os; from codex_cli_bin import bundled_codex_path; os.symlink(bundled_codex_path(), "/usr/local/bin/codex")'
COPY agent_service/ /app/agent_service/
WORKDIR /app/agent_service
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    HOME=/data/codex CODEX_HOME=/data/codex
CMD ["uvicorn", "codex_voice.app:create_app", "--factory", "--host", "127.0.0.1", "--port", "8765"]
