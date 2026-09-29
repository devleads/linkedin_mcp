# LinkedIn MCP Server Dockerfile
# Uses Python 3.11 with Playwright/Patchright browser dependencies

FROM python:3.11-slim-bookworm

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies for Chromium/Playwright and PostgreSQL
RUN apt-get update && apt-get install -y --no-install-recommends \
    # PostgreSQL client library (required by psycopg)
    libpq5 \
    # Chromium dependencies
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libatspi2.0-0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    # Fonts
    fonts-liberation \
    fonts-noto-color-emoji \
    # Utilities
    curl \
    wget \
    ca-certificates \
    # For headless display (Xvfb)
    xvfb \
    xauth \
    # Clean up
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast Python package management
RUN pip install uv

# Create app directory
WORKDIR /app

# Copy all source code (needed for hatchling to build package)
COPY . .

# Install Python dependencies
RUN uv sync --frozen

# Install the real Chrome channel used by the persistent runtime.
RUN uv run patchright install chrome

# Create an unprivileged service account and its durable browser profile root.
RUN groupadd --system linkedin-mcp \
    && useradd --system --gid linkedin-mcp --home-dir /app linkedin-mcp \
    && mkdir -p /app/data/browser_state \
    && chown -R linkedin-mcp:linkedin-mcp /app

# Copy entrypoint script that starts Xvfb before the Python process.
COPY docker-entrypoint.sh ./docker-entrypoint.sh
RUN chmod +x ./docker-entrypoint.sh

USER linkedin-mcp

# Expose MCP server port
EXPOSE 8765

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8765/health || exit 1

# Default environment for Xvfb (can be overridden in docker-compose)
ENV USE_XVFB=1

# Use entrypoint script that starts Xvfb with error checking and fallback
CMD ["./docker-entrypoint.sh"]
