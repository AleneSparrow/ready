FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates unzip && \
    curl https://rclone.org/install.sh | bash && \
    apt-get purge -y curl unzip && apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV CACHE_DIR=/data/cache
ENV CATALOG_DB_PATH=/data/flibusta_catalog.db

CMD ["python", "-m", "bot.main"]
