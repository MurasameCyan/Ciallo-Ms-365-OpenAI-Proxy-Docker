#!/bin/bash
set -e

# Prefix all container stdout/stderr lines with ISO-like local time for readable docker logs.
if [ -z "${LOG_TS_PREFIXED:-}" ]; then
    export LOG_TS_PREFIXED=1
    exec > >(while IFS= read -r line; do printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$line"; done) 2>&1
fi

CDP_PORT="${CHROME_CDP_PORT:-9222}"
CHROME_PROFILE="/chrome-profile"
AUTO_REFRESH="${AUTO_REFRESH:-true}"

# --- Root-only section: fix permissions and clean stale locks ---
if [ "$(id -u)" = "0" ]; then
    # Fix volume ownership (Docker volumes default to root:root on first mount)
    mkdir -p "$CHROME_PROFILE" 2>/dev/null || true
    chown -R app:app "$CHROME_PROFILE" 2>/dev/null || true
    rm -f "$CHROME_PROFILE/SingletonLock" "$CHROME_PROFILE/SingletonCookie" "$CHROME_PROFILE/SingletonSocket" 2>/dev/null || true

    # Prepare token storage on tmpfs-backed volume
    mkdir -p /home/app/token 2>/dev/null || true
    chown -R app:app /home/app/token 2>/dev/null || true

    # Re-exec as app user via gosu (does NOT preserve environment wholesale — safer)
    export HOME=/home/app
    exec gosu app "$0" "$@"
fi

# --- Below runs as app user ---

# Detect Chromium binary (name varies by distro)
if [ -n "${CHROME_BIN:-}" ] && command -v "$CHROME_BIN" &> /dev/null; then
    CHROME_BIN="$CHROME_BIN"
elif command -v chromium &> /dev/null; then
    CHROME_BIN="chromium"
elif command -v chromium-browser &> /dev/null; then
    CHROME_BIN="chromium-browser"
elif command -v google-chrome-stable &> /dev/null; then
    CHROME_BIN="google-chrome-stable"
elif command -v google-chrome &> /dev/null; then
    CHROME_BIN="google-chrome"
else
    echo "WARNING: No Chrome/Chromium binary found. Starting server without auto-refresh."
    CHROME_BIN=""
fi

STARTUP_CDP="false"
# ENABLE_ADMIN_CDP (default false) gates the SHARED admin Chromium on the primary
# port (9222) and the admin endpoints that depend on it. Pool deployments leave it
# off: per-account Chromium (9322+) and the keepalive/cookie-refresh loop run from
# the app startup hook regardless of this flag, so turning it off does NOT disable
# per-account refresh. Set ENABLE_ADMIN_CDP=true to restore the shared 9222 browser
# (single-tenant startup capture + /admin/token/auto-capture, /admin/cookie/inject,
# /admin/chromium/* endpoints).
ENABLE_ADMIN_CDP="${ENABLE_ADMIN_CDP:-false}"
if [ -n "$CHROME_BIN" ] && [ "$AUTO_REFRESH" = "true" ] && [ "$ENABLE_ADMIN_CDP" = "true" ]; then
    STARTUP_CDP="true"
fi

# Start Chrome headless + CDP (only if binary found, AUTO_REFRESH is true, and a startup token exists)
if [ "$STARTUP_CDP" = "true" ]; then
    CHROME_LOG="/tmp/chromium-cdp.log"
    : > "$CHROME_LOG"
    echo "Starting $CHROME_BIN headless on CDP port $CDP_PORT ..."
    "$CHROME_BIN" \
        --headless \
        --no-sandbox \
        --remote-debugging-address=127.0.0.1 \
        --remote-debugging-port="$CDP_PORT" \
        --user-data-dir="$CHROME_PROFILE" \
        --no-first-run \
        --disable-gpu \
        --disable-dev-shm-usage \
        --disable-background-networking \
        --disable-sync \
        --no-default-browser-check \
        --disable-features=InfiniteRestore,MediaRouter,DialMediaRouteProvider,TranslateUI \
        --disable-breakpad \
        --disable-crash-reporter \
        --disable-in-process-stack-traces \
        --no-experiments \
        "about:blank" > "$CHROME_LOG" 2>&1 &

    CHROME_PID=$!
    echo "Chromium started with PID $CHROME_PID"

    # Wait for Chrome CDP to be ready
    echo "Waiting for Chromium CDP on port $CDP_PORT ..."
    for i in $(seq 1 30); do
        if curl -sf "http://localhost:$CDP_PORT/json/version" >/dev/null 2>&1; then
            echo "Chromium CDP ready."
            break
        fi
        if ! kill -0 "$CHROME_PID" 2>/dev/null; then
            echo "WARNING: Chromium process exited before CDP became ready. Last Chromium log lines:"
            tail -n 80 "$CHROME_LOG" || true
            break
        fi
        if [ $i -eq 30 ]; then
            echo "WARNING: Chromium CDP did not become ready in 30s. Continuing without CDP."
            if ! kill -0 "$CHROME_PID" 2>/dev/null; then
                echo "WARNING: Chromium process exited before CDP became ready. Last Chromium log lines:"
                tail -n 80 "$CHROME_LOG" || true
            else
                echo "Last Chromium log lines:"
                tail -n 80 "$CHROME_LOG" || true
            fi
        fi
        sleep 1
    done
fi

# Build serve command arguments
# Use --no-launch-edge to prevent Python from launching another Chromium instance
SERVE_ARGS="--host 0.0.0.0 --port 8000 --no-launch-edge"

if [ "$STARTUP_CDP" = "true" ]; then
    SERVE_ARGS="$SERVE_ARGS --cdp-port $CDP_PORT --refresh-before-seconds ${REFRESH_BEFORE_SECONDS:-300}"
else
    SERVE_ARGS="$SERVE_ARGS --no-auto-refresh --no-capture-on-start"
fi

echo "Starting copilot-openai-proxy serve $SERVE_ARGS"
exec uv run copilot-openai-proxy serve $SERVE_ARGS
