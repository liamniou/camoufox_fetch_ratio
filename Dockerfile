# Use a base image with Python installed
FROM python:3.9-slim-buster

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    build-essential \
    libpcap-dev \
    libgtk-3-0 \
    libasound2 \
    libx11-xcb1 \
    libxcb-xkb1 \
    libxkbcommon-x11-0 \
    libxcb-icccm4 \
    libxcb-image0 \
    libxcb-keysyms1 \
    libxcb-randr0 \
    libxcb-render-util0 \
    libxcb-xinerama0 \
    && rm -rf /var/lib/apt/lists/* && apt-get clean

RUN pip install 'camoufox[geoip]' requests prometheus-client --no-cache-dir

RUN python -m camoufox fetch

RUN python -m camoufox --help

COPY main.py ./

CMD ["python", "main.py"]
