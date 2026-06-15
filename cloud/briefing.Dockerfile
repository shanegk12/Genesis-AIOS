# Morning briefing — short-lived Cloud Run Job (runs once at 8 AM ET, then exits).
# Reads the PM board (Firestore REST), voices per-person DMs with Claude, posts to Slack.
FROM python:3.12-slim

RUN pip install --no-cache-dir anthropic google-auth requests

WORKDIR /app
COPY scripts/morning_briefing.py scripts/slack.py /app/scripts/

# --send actually delivers; drop it to dry-run. Firestore auth comes from the
# job's runtime service account (needs roles/datastore.viewer); SLACK_BOT_TOKEN
# and ANTHROPIC_API_KEY are injected as secrets at deploy time.
CMD ["python", "scripts/morning_briefing.py", "--send"]
