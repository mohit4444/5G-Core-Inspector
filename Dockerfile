FROM node:22-bookworm-slim AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/index.html frontend/vite.config.js ./
COPY frontend/src ./src
RUN npm run build

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements-runtime.txt ./
RUN pip install --no-cache-dir -r requirements-runtime.txt \
    && groupadd --gid 10001 inspector \
    && useradd --uid 10001 --gid inspector --no-create-home inspector
COPY app.py engine.py failure_rules.py pdu.py ./
COPY adapters ./adapters
COPY --from=frontend /build/static ./static
COPY tests/fixtures/success.log tests/fixtures/oai-success.log ./examples/
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2).close()"]
ENTRYPOINT ["python", "app.py", "--host", "0.0.0.0"]
CMD ["--replay", "/app/examples/success.log", "--year", "2026"]
