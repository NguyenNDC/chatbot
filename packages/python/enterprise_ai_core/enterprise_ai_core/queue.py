from functools import lru_cache

from celery import Celery

from .config import get_settings


@lru_cache
def get_celery_app() -> Celery:
    settings = get_settings()
    app = Celery(
        settings.service_name,
        broker=settings.rabbitmq_url,
        backend=settings.redis_url,
    )
    app.conf.update(
        task_routes={
            "document.parse": {"queue": "document.parse"},
            "document.chunk": {"queue": "document.chunk"},
            "document.embed": {"queue": "document.embed"},
            "graph.extract": {"queue": "graph.extract"},
            "graph.upsert": {"queue": "graph.upsert"},
        },
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        result_expires=3600,
    )
    return app

