# Keep the multi-platform base reproducible; refresh the digest with security updates.
ARG PYTHON_IMAGE=python:3.13-slim@sha256:09a17cad02668ae61ece136b4fd36ac3849e14f670ebedb637ea3e15580525bc
FROM ${PYTHON_IMAGE} AS builder

# Prevent interactive prompts during package installation.
ENV DEBIAN_FRONTEND=noninteractive

# Native build fallback for platforms without compatible emulator/pygame wheels.
# None of these tools or development headers are copied into the runtime image.
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
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements-docker.txt ./
RUN python -m pip wheel --no-cache-dir --wheel-dir /wheels -r requirements-docker.txt

COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip wheel --no-cache-dir --no-deps --wheel-dir /wheels .

FROM ${PYTHON_IMAGE} AS runtime
ENV DEBIAN_FRONTEND=noninteractive

# Retain the tested graphical stack, including fonts and pyglet's GLU dependency.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglu1-mesa \
    fontconfig \
    procps \
    tigervnc-standalone-server \
    tigervnc-tools \
    novnc \
    websockify \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY README.md requirements-docker.txt ./

# A bind mount from the builder avoids retaining the wheel archive in an image layer.
# Installing into /usr/local preserves existing custom-ROM mount paths.
RUN --mount=type=bind,from=builder,source=/wheels,target=/wheels \
    python -m pip install --no-cache-dir --no-index /wheels/*.whl \
    && python -m pip check

ARG MARIO_UID=1000
ARG MARIO_GID=1000
RUN groupadd --gid "$MARIO_GID" mario \
    && useradd --uid "$MARIO_UID" --gid "$MARIO_GID" --create-home mario \
    && mkdir -p /app/artifacts \
    && chown mario:mario /app/artifacts

# Virtual display and VNC configuration.
ENV DISPLAY=:1
ENV DISPLAY_WIDTH=1440
ENV DISPLAY_HEIGHT=810
ENV VNC_PORT=5901
ENV NOVNC_PORT=6080
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV SDL_AUDIODRIVER=dummy
# Runtime state (VNC password file, font caches) remains writable with a read-only root.
ENV HOME=/tmp/mario

# Expose the noVNC web port.
EXPOSE 6080

# Copy the entrypoint that starts TigerVNC, noVNC, and the agent.
COPY --chmod=755 entrypoint.sh /usr/local/bin/entrypoint.sh

USER mario
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
