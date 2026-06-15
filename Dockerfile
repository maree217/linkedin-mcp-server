# -- Stage 1: Build virtual environment --
FROM python:3.13.13-slim-bookworm@sha256:355bfa66770995d7e9a0da4b3473b44d0cb451f6b56f5615ad9c39e3c4eca03f AS builder

COPY --from=ghcr.io/astral-sh/uv:latest@sha256:ff07b86af50d4d9391d9daf4ff89ce427bc544f9aae87057e69a1cc0aa369946 /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --no-dev --no-editable --compile-bytecode

COPY . .
RUN uv sync --frozen --no-dev --no-editable --compile-bytecode


# -- Stage 2: Production runtime --
FROM python:3.13.13-slim-bookworm@sha256:355bfa66770995d7e9a0da4b3473b44d0cb451f6b56f5615ad9c39e3c4eca03f

RUN useradd -m -s /bin/bash pwuser

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/patchright

RUN patchright install-deps chromium && \
    patchright install chromium && \
    chmod -R 755 /opt/patchright && \
    rm -rf /var/lib/apt/lists/*

USER pwuser

ENTRYPOINT ["python", "-m", "linkedin_mcp_server"]
CMD []
