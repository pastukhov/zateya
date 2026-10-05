# syntax=docker/dockerfile:1
FROM python:3.12-slim

ARG ZATEYA_UID=1000
ARG ZATEYA_GID=1000

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential ca-certificates cmake curl git libffi-dev libssl-dev ninja-build pkg-config \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir platformio==6.2.0 cryptography==46.0.5

RUN groupadd --gid "${ZATEYA_GID}" builder \
    && useradd --uid "${ZATEYA_UID}" --gid builder --create-home builder \
    && mkdir -p /work /cache /releases /signing \
    && chown -R builder:builder /work /cache /releases

COPY --chown=builder:builder firmware/ /work/firmware/
COPY --chown=builder:builder deploy/firmware/build-release.py /work/build-release.py
ENV PLATFORMIO_CORE_DIR=/cache HOME=/home/builder PYTHONUNBUFFERED=1
USER builder
WORKDIR /work
ENTRYPOINT ["python", "/work/build-release.py"]
