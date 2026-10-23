FROM python:3.12-slim

WORKDIR /app
RUN pip install --no-cache-dir uv==0.12.10 \
    && useradd --create-home --uid 10001 gateway
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN uv sync --locked --no-dev \
    && mkdir data && chown gateway:gateway data

USER gateway
EXPOSE 8091
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8091/health', timeout=3)"
CMD ["/app/.venv/bin/axonhub", "--host", "0.0.0.0"]
