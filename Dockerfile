FROM python:3.13-slim

# Prevent interactive prompts during package installation.
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies:
# - build tools for nes-py native extension
# - SDL libraries for pygame
# - virtual X display and VNC stack for the browser dashboard
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    git \
    libsdl2-dev \
    libsdl2-image-dev \
    libsdl2-mixer-dev \
    libsdl2-ttf-dev \
    libportmidi-dev \
    libfreetype6-dev \
    pkg-config \
    libglu1-mesa \
    fontconfig \
    tigervnc-standalone-server \
    tigervnc-tools \
    novnc \
    websockify \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy packaging metadata and source first so pip can install the project.
COPY pyproject.toml README.md ./
COPY src ./src

# Install the package with the Mario extras. This also installs gym-super-mario-bros
# which bundles the required ROM files.
RUN pip install --no-cache-dir -e ".[mario]"

# Virtual display and VNC configuration.
ENV DISPLAY=:1
ENV DISPLAY_WIDTH=1440
ENV DISPLAY_HEIGHT=810
ENV VNC_PORT=5901
ENV NOVNC_PORT=6080
ENV VNC_PASSWORD=mario
ENV PYTHONUNBUFFERED=1
ENV SDL_AUDIODRIVER=dummy

# Expose the noVNC web port.
EXPOSE 6080

# Copy the entrypoint that starts TigerVNC, noVNC, and the agent.
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
