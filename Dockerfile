FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY startup.sh /startup.sh
RUN chmod +x /startup.sh

ENV PYTHONUNBUFFERED=1
EXPOSE 8080

CMD ["/startup.sh"]
