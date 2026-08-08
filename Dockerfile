FROM python:3.11-slim-bookworm

# Install Chromium (available on both amd64 and arm64 via Debian repos).
# NOTE: full Chromium only. The headless-shell package pulls a different
# Chromium build that fails to bind the CDP debug port during the on-demand
# refresh flow ("[Errno 99] Cannot assign requested address"), so it must not
# be installed alongside full Chromium.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        chromium \
        chromium-common \
        fonts-wqy-zenhei \
        gosu \
        curl \
    && rm -rf /var/lib/apt/lists/* \
    && echo "Chromium version: $(chromium --version || echo 'unknown')"

# Install uv package manager
RUN pip install --no-cache-dir uv

# Create non-root user and directories (merged into single RUN to reduce layers)
RUN groupadd -r app && useradd -r -g app -d /home/app -s /sbin/nologin app && \
    mkdir -p /chrome-profile /home/app/token /home/app /app && \
    chown -R app:app /chrome-profile /home/app /app

WORKDIR /app

# Copy dependency files first for Docker layer caching
COPY --chown=app:app pyproject.toml .
COPY --chown=app:app uv.lock .

# Unattended refresh for consumer (personal-account) Copilot needs Camoufox, a
# Firefox fork -- the consumer endpoint challenges Chromium TLS fingerprints and
# answers Firefox ones, so the Chromium already installed above cannot do this
# job. Off by default: it adds ~936 MB, which an M365-only deployment should not
# carry. Without it consumer accounts still work; they just need the user to
# re-push credentials from the userscript instead of renewing on their own.
#   docker build --build-arg WITH_CAMOUFOX=true ...
ARG WITH_CAMOUFOX=false

# Install Python dependencies as app user (avoids chown -R producing extra layer)
USER app
RUN if [ "$WITH_CAMOUFOX" = "true" ]; then \
      uv sync --frozen --no-dev --extra camoufox; \
    else \
      uv sync --frozen --no-dev; \
    fi

# Fetch the browser at build time, as the app user so it lands somewhere that
# user can read. Doing it here rather than on first use keeps a ~936 MB download
# out of the first request's latency, and off the runtime network path entirely.
#
# The path is asserted because it has to agree with what the app user resolves at
# runtime, and nothing in this file states it: the cache dir comes from $HOME,
# which BuildKit derives from the passwd entry on USER and gosu derives again on
# the entrypoint's re-exec. They agree today (both /home/app). If a change to the
# user or HOME ever breaks that, this fails the build instead of surfacing as a
# surprise re-download during the first refresh.
RUN if [ "$WITH_CAMOUFOX" = "true" ]; then \
      uv run --no-sync python -m camoufox fetch && \
      test -d /home/app/.cache/camoufox/browsers && \
      echo "Camoufox fetched"; \
    fi
USER root

# Camoufox runs under a virtual display rather than true headless: headless
# Firefox is itself a detectable signal, and not being detected is the entire
# reason this path uses Firefox. xvfb is only needed for that.
RUN if [ "$WITH_CAMOUFOX" = "true" ]; then \
      apt-get update && \
      apt-get install -y --no-install-recommends xvfb libgtk-3-0 libasound2 && \
      rm -rf /var/lib/apt/lists/*; \
    fi

# Build-time commit for the admin sidebar GitHub badge.
# CI passes github.sha; local: docker build --build-arg GIT_COMMIT=$(git rev-parse HEAD) ...
# Image has no .git, so env + baked file are the only reliable sources at runtime.
ARG GIT_COMMIT=
RUN if [ -n "$GIT_COMMIT" ]; then \
      printf '%s\n' "$GIT_COMMIT" > /app/GIT_COMMIT && \
      chown app:app /app/GIT_COMMIT; \
    fi
ENV GIT_COMMIT=${GIT_COMMIT}

# Copy project source and entrypoint
COPY --chown=app:app src/ src/
COPY --chown=app:app entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Persist Chrome user data (login state)
VOLUME /chrome-profile

# NOTE: /home/app/token is mounted by docker-compose (a named volume in the
# shipped file), deliberately not VOLUME here. Declaring VOLUME would shadow a
# tmpfs mount with a root:root named volume and break app-user writes, so the
# choice is left to compose.
#
# It must be durable, not tmpfs: TOKEN_DIR/profiles holds the per-account browser
# profiles, and the consumer one carries the Microsoft account session that the
# unattended refresh renews from. Losing it costs an interactive sign-in.

# Environment variables (do NOT set M365_ACCESS_TOKEN or ADMIN_PASSWORD here — they may leak into image layers)
ENV M365_TIME_ZONE="Asia/Shanghai"
ENV M365_MODEL_ALIAS="m365-copilot"
ENV CHROME_CDP_PORT=9222
ENV AUTO_REFRESH="true"
ENV REFRESH_BEFORE_SECONDS=300
ENV IDLE_TIMEOUT_MINUTES=30
ENV TOKEN_DIR="/home/app/token"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -sf http://localhost:8000/healthz || exit 1

# Start as root to fix volume permissions, then drop to app user via gosu in entrypoint
ENTRYPOINT ["/entrypoint.sh"]
