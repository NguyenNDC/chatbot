FROM python:3.12-slim

ARG SERVICE_PATH
ARG SERVICE_PORT=8000
ARG REQUIREMENTS_GROUPS=base
ARG INSTALL_OCR_SYSTEM_DEPS=false

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/packages/python/enterprise_ai_core
ENV SERVICE_PATH=${SERVICE_PATH}
ENV SERVICE_PORT=${SERVICE_PORT}
ENV HF_HOME=/opt/hf-cache
ENV TRANSFORMERS_CACHE=/opt/hf-cache/transformers
ENV SENTENCE_TRANSFORMERS_HOME=/opt/hf-cache/sentence-transformers

WORKDIR /app

RUN if [ "$INSTALL_OCR_SYSTEM_DEPS" = "true" ]; then \
      apt-get update \
      && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-vie \
        libgl1 \
        libglib2.0-0 \
      && rm -rf /var/lib/apt/lists/*; \
    fi

COPY requirements /app/requirements
COPY requirements.txt /app/requirements.txt
RUN set -eux; \
    for group in $(echo "$REQUIREMENTS_GROUPS" | tr ',' ' '); do \
      pip install --no-cache-dir -r "/app/requirements/${group}.txt"; \
    done

COPY . /app

RUN mkdir -p /opt/hf-cache

EXPOSE ${SERVICE_PORT}

ENTRYPOINT ["sh", "/app/infra/docker/entrypoint.sh"]
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${SERVICE_PORT} --app-dir ${SERVICE_PATH}"]
