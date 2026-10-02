FROM python:3.9-slim-bookworm

# System deps for camoufox / playwright
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libgtk-3-0 libdbus-glib-1-2 libxt6 libasound2 \
        libx11-xcb1 libxcomposite1 libxdamage1 libxrandr2 \
        libgbm1 libpango-1.0-0 libcairo2 libatk1.0-0 \
        libatk-bridge2.0-0 libxkbcommon0 libxshmfence1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install camoufox browser binary
RUN python -c "import camoufox; camoufox.sync_api"  || true
RUN python -m camoufox fetch --browserforge || true

COPY main.py .

CMD ["python", "main.py"]
