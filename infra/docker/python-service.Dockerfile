FROM python:3.12-slim

ARG SERVICE_PATH
ARG SERVICE_PORT=8000
ARG PRELOAD_BGE_M3=false

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/packages/python/enterprise_ai_core
ENV SERVICE_PATH=${SERVICE_PATH}
ENV SERVICE_PORT=${SERVICE_PORT}
ENV HF_HOME=/opt/hf-cache
ENV TRANSFORMERS_CACHE=/opt/hf-cache/transformers
ENV SENTENCE_TRANSFORMERS_HOME=/opt/hf-cache/sentence-transformers

WORKDIR /app

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-vie \
    libgl1 \
    libglib2.0-0 \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

RUN mkdir -p /opt/hf-cache
RUN if [ "$PRELOAD_BGE_M3" = "true" ]; then python /app/infra/scripts/preload_bge_m3.py; fi

EXPOSE ${SERVICE_PORT}

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${SERVICE_PORT} --app-dir ${SERVICE_PATH}"]
