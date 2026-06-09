# API + worker no mesmo container (dev ou VM única).
# Produção com worker já na AWS: use Dockerfile.api — ver deploy/aws/README.md
FROM python:3.11-slim

RUN apt-get update \
  && apt-get install -y --no-install-recommends poppler-utils \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY prompt.txt .
COPY src ./src
COPY run_api.py run_worker.py ./
COPY scripts/start-production.sh ./scripts/

ENV APP_ENV=production
ENV APP_HOST=0.0.0.0
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import os,urllib.request; p=os.environ.get('PORT','8000'); urllib.request.urlopen(f'http://127.0.0.1:{p}/health')"

CMD ["sh", "scripts/start-production.sh"]
