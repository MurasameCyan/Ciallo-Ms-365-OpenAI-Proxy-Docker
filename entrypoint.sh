#!/bin/bash
set -e

CDP_PORT="${CHROME_CDP_PORT:-9222}"
CHROME_PROFILE="/chrome-profile"
AUTO_REFRESH="${AUTO_REFRESH:-true}"

# 创建 Chrome profile 目录
mkdir -p "$CHROME_PROFILE"

# 启动 Chrome headless + CDP
echo "Starting Chrome headless on CDP port $CDP_PORT ..."
google-chrome-stable \
  --headless=new \
  --no-sandbox \
  --disable-gpu \
  --remote-debugging-port="$CDP_PORT" \
  --user-data-dir="$CHROME_PROFILE" \
  --no-first-run \
  --disable-dev-shm-usage \
  "https://m365.cloud.microsoft/chat" &

# 等待 Chrome 启动
echo "Waiting for Chrome CDP on port $CDP_PORT ..."
for i in $(seq 1 30); do
  if curl -s "http://localhost:$CDP_PORT/json" > /dev/null 2>&1; then
    echo "Chrome CDP ready."
    break
  fi
  sleep 1
done

# 构建 serve 命令参数
SERVE_ARGS="--host 0.0.0.0 --port 8000 --cdp-port $CDP_PORT"

if [ "$AUTO_REFRESH" = "true" ]; then
  SERVE_ARGS="$SERVE_ARGS --refresh-before-seconds ${REFRESH_BEFORE_SECONDS:-300}"
else
  SERVE_ARGS="$SERVE_ARGS --no-auto-refresh"
fi

# 首次启动时如果没有 token，尝试自动捕获
if [ -z "$M365_ACCESS_TOKEN" ]; then
  echo "No M365_ACCESS_TOKEN set. Attempting auto-capture from Chrome CDP ..."
  # 给 Copilot 页面一些加载时间
  sleep 5
fi

echo "Starting copilot-openai-proxy serve $SERVE_ARGS"
exec uv run copilot-openai-proxy serve $SERVE_ARGS
