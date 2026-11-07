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
    --safety-mode "${SAFETY_MODE:-off}"
    --min-confidence "${MIN_CONFIDENCE:-0.8}"
    --danger-threshold "${DANGER_THRESHOLD:-0.5}"
    --safety-margin-frames "${SAFETY_MARGIN_FRAMES:-6}"
    --artifacts-dir /app/artifacts
)
if [ -n "${MODEL:-}" ]; then args+=(--model "$MODEL"); fi
if [ -n "${BASE_URL:-}" ]; then args+=(--base-url "$BASE_URL"); fi
args+=("$@")

# Honor the final --display override, including --display=none, before starting X.
display_mode="${GAME_DISPLAY:-dashboard}"
for ((i=0; i<${#args[@]}; i++)); do
    case "${args[i]}" in
        --display) display_mode="${args[i+1]:-}" ;;
        --display=*) display_mode="${args[i]#*=}" ;;
        --help|-h) exec typesafe-mario "${args[@]}" ;;
    esac
done
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
mkdir -p ~/.vnc
printf '%s' "$VNC_PASSWORD" | tigervncpasswd -f > ~/.vnc/passwd
chmod 600 ~/.vnc/passwd
Xtigervnc :1 -geometry "${DISPLAY_WIDTH}x${DISPLAY_HEIGHT}" -depth 24 \
    -rfbport "$VNC_PORT" -PasswordFile ~/.vnc/passwd -localhost yes &
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
sleep 1
kill -0 "$NOVNC_PID" 2>/dev/null || { echo "noVNC failed to start" >&2; exit 1; }

echo "Open http://localhost:$NOVNC_HOST_PORT/vnc.html and click Connect"
echo "VNC password: $VNC_PASSWORD (trusted local networks only; no TLS)"
exec typesafe-mario "${args[@]}"
