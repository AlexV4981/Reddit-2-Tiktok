FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core libgomp1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md config.example.json ./
COPY src/reddit2tiktok/ ./src/reddit2tiktok/
RUN python -m pip install torch --index-url https://download.pytorch.org/whl/cpu \
    && python -m pip install '.[kokoro]' \
    && python -m spacy download en_core_web_sm \
    && python -m pip check
RUN useradd --create-home --uid 1000 app \
    && mkdir /workspace \
    && chown app:app /workspace
USER 1000:1000
WORKDIR /workspace
ENTRYPOINT ["reddit2tiktok", "--config", "/workspace/config.json"]
CMD []

FROM runtime AS test
USER root
WORKDIR /app
RUN python -m pip install '.[dev]'
COPY tests/ ./tests/
USER 1000:1000
ENTRYPOINT ["python", "-m", "pytest"]
CMD ["-q", "-p", "no:cacheprovider", "--basetemp=/tmp/r2t-tests"]

FROM runtime AS production
