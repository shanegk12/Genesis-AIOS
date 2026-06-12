# 24/7 Bez on Cloud Run — Slack Socket Mode agent with full dev tooling.
FROM python:3.12-slim

# Tooling Bez needs to actually work: git, node/npm, gh, firebase-tools.
RUN apt-get update && apt-get install -y --no-install-recommends \
      git curl ca-certificates gnupg \
 && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
      | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
 && echo "deb [signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
      > /etc/apt/sources.list.d/github-cli.list \
 && apt-get update && apt-get install -y --no-install-recommends gh \
 && npm i -g firebase-tools \
 && pip install --no-cache-dir slack_bolt anthropic \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY scripts/bez_agent.py scripts/bez_socket.py /app/scripts/
COPY cloud/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Bez operates on the cloned platform repo by default.
ENV BEZ_CWD=/app/repos/GK12-Platform
ENV BEZ_AIOS=/app/repos/AIOS

CMD ["/app/entrypoint.sh"]
