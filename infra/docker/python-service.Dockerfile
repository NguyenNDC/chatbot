FROM python:3.12-slim

ARG SERVICE_PATH
ARG SERVICE_PORT=8000

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/packages/python/enterprise_ai_core
ENV SERVICE_PATH=${SERVICE_PATH}
ENV SERVICE_PORT=${SERVICE_PORT}

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

EXPOSE ${SERVICE_PORT}

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${SERVICE_PORT} --app-dir ${SERVICE_PATH}"]
