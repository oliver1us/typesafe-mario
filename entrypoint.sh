#!/bin/bash
set -euo pipefail

# CLI arguments appended below take precedence over these environment defaults.
args=(play
    --backend "${BACKEND:-openrouter}"
    --policy "${POLICY:-typesafe}"
    --env "${ENV_ID:-SuperMarioBros-1-1-v0}"
    --frames-per-decision "${FRAMES_PER_DECISION:-8}"
    --max-decisions "${MAX_DECISIONS:-2000}"
    --seed "${SEED:-123}"
    --display "${GAME_DISPLAY:-dashboard}"
    --game-width "${DISPLAY_WIDTH:-1440}"
    --game-height "${DISPLAY_HEIGHT:-810}"
    --safety-mode "${SAFETY_MODE:-off}"
    --min-confidence "${MIN_CONFIDENCE:-0.8}"
    --danger-threshold "${DANGER_THRESHOLD:-0.5}"
    --safety-margin-frames "${SAFETY_MARGIN_FRAMES:-6}"
    --artifacts-dir /app/artifacts
)
if [ -n "${MODEL:-}" ]; then args+=(--model "$MODEL"); fi
if [ -n "${BASE_URL:-}" ]; then args+=(--base-url "$BASE_URL"); fi
case "${SHOW_TRAJECTORIES:-false}" in
    true|1|yes|on) args+=(--trajectories) ;;
    false|0|no|off) args+=(--no-trajectories) ;;
    *) echo "SHOW_TRAJECTORIES must be true/false (or 1/0, yes/no, on/off)" >&2; exit 2 ;;
esac
args+=("$@")

# Honor the final --display override, including --display=none, before starting X.
display_mode="${GAME_DISPLAY:-dashboard}"
artifacts_dir=/app/artifacts
for ((i=0; i<${#args[@]}; i++)); do
    case "${args[i]}" in
        --display) display_mode="${args[i+1]:-}" ;;
        --display=*) display_mode="${args[i]#*=}" ;;
        --artifacts-dir) artifacts_dir="${args[i+1]:-}" ;;
        --artifacts-dir=*) artifacts_dir="${args[i]#*=}" ;;
        --help|-h) exec typesafe-mario "${args[@]}" ;;
    esac
done
if ! mkdir -p -- "$artifacts_dir" 2>/dev/null || [ ! -w "$artifacts_dir" ]; then
    echo "Artifacts directory is not writable: $artifacts_dir" >&2
    echo "Make the bind mount writable by container UID $(id -u):GID $(id -g); see README.md for migration steps." >&2
    exit 2
fi
if [ "$display_mode" = none ]; then
    exec typesafe-mario "${args[@]}"
fi

DISPLAY_WIDTH="${DISPLAY_WIDTH:-1440}"
DISPLAY_HEIGHT="${DISPLAY_HEIGHT:-810}"
VNC_PORT="${VNC_PORT:-5901}"
NOVNC_PORT="${NOVNC_PORT:-6080}"
NOVNC_HOST_PORT="${NOVNC_HOST_PORT:-$NOVNC_PORT}"
VNC_PASSWORD="${VNC_PASSWORD:-mario}"

# TigerVNC supplies the X display itself; do not start Xvfb on the same display.
rm -f /tmp/.X1-lock /tmp/.X11-unix/X1
mkdir -m 1777 -p /tmp/.X11-unix
mkdir -p "$HOME/.vnc"
chmod 700 "$HOME/.vnc"
saved_umask=$(umask)
umask 077
printf '%s' "$VNC_PASSWORD" | tigervncpasswd -f > ~/.vnc/passwd
chmod 600 ~/.vnc/passwd
umask "$saved_umask"
Xtigervnc :1 -geometry "${DISPLAY_WIDTH}x${DISPLAY_HEIGHT}" -depth 24 \
    -rfbport "$VNC_PORT" -PasswordFile ~/.vnc/passwd -localhost yes -nolisten tcp &
VNC_PID=$!

# Fail clearly if the graphical service cannot start.
for _ in {1..50}; do
    kill -0 "$VNC_PID" 2>/dev/null || { echo "TigerVNC failed to start" >&2; exit 1; }
    if [ -S /tmp/.X11-unix/X1 ]; then break; fi
    sleep 0.1
done
[ -S /tmp/.X11-unix/X1 ] || { echo "Timed out waiting for the X display" >&2; exit 1; }
/usr/share/novnc/utils/novnc_proxy \
    --vnc "localhost:$VNC_PORT" --listen "$NOVNC_PORT" --web /usr/share/novnc &
NOVNC_PID=$!
novnc_ready=false
for _ in {1..50}; do
    kill -0 "$NOVNC_PID" 2>/dev/null || { echo "noVNC failed to start" >&2; exit 1; }
    if python -c 'import sys, urllib.request; urllib.request.urlopen(f"http://127.0.0.1:{sys.argv[1]}/vnc.html", timeout=0.2).close()' "$NOVNC_PORT" >/dev/null 2>&1; then
        novnc_ready=true
        break
    fi
    sleep 0.1
done
[ "$novnc_ready" = true ] || { echo "Timed out waiting for noVNC" >&2; exit 1; }

echo "Open http://localhost:$NOVNC_HOST_PORT/vnc.html and click Connect"
echo "VNC authentication is enabled (configure VNC_PASSWORD; trusted local access only, no TLS)."
exec typesafe-mario "${args[@]}"
