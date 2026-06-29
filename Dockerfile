FROM python:3.11-slim

# 安装 uv + Chrome headless + CDP 依赖
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        gnupg2 \
        && \
    curl -fsSL https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg && \
    echo "deb [arch=amd64,arm64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends google-chrome-stable && \
    apt-get purge -y gnupg2 && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

# 安装 uv 包管理器
RUN pip install --no-cache-dir uv

WORKDIR /app

# 先复制依赖定义文件，利用 Docker 缓存层
COPY pyproject.toml .
COPY uv.lock .

# 安装 Python 依赖
RUN uv sync --frozen --no-dev

# 复制项目源码
COPY src/ src/

# 复制启动脚本
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# 持久化 Chrome 用户数据（保存登录状态）
VOLUME /chrome-profile

# 环境变量
ENV M365_ACCESS_TOKEN=""
ENV M365_TIME_ZONE="Asia/Tokyo"
ENV M365_MODEL_ALIAS="m365-copilot"
ENV CHROME_CDP_PORT=9222
ENV AUTO_REFRESH="true"
ENV REFRESH_BEFORE_SECONDS=300

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
