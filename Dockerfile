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

# camoufox 0.3.9 breaks on newer browser builds ("Unknown property navigator.appCodeName"),
# so replace the just-fetched latest build with a pinned one.
ARG CAMOUFOX_BROWSER=135.0.1-beta.24
RUN python -c "import io,json,os,urllib.request,zipfile; v='${CAMOUFOX_BROWSER}'; d='/root/.cache/camoufox'; \
u='https://github.com/daijro/camoufox/releases/download/v%s/camoufox-%s-lin.x86_64.zip'%(v,v); \
import shutil; shutil.rmtree(d,ignore_errors=True); os.makedirs(d); \
zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(u).read())).extractall(d); \
ver,rel=v.split('-',1); json.dump({'version':ver,'release':rel},open(d+'/version.json','w'))" \
    && chmod -R 755 /root/.cache/camoufox \
    && python -m camoufox version

COPY main.py .

CMD ["python", "main.py"]
