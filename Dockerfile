FROM python:3.12-slim

WORKDIR /app

# Install curl for healthcheck
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy project files
COPY pyproject.toml uv.lock ./
COPY *.py ./

# Install dependencies (including service extras)
RUN uv sync --frozen --no-dev --extra service

# Expose port
EXPOSE 8000

# Run uvicorn (command specified in docker-compose.yml)
CMD ["uv", "run", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
