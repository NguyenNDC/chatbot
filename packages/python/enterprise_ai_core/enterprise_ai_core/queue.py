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
            "document.dead_letter": {"queue": settings.worker_dead_letter_queue},
        },
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        result_expires=3600,
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        worker_enable_remote_control=False,
        worker_send_task_events=False,
        task_send_sent_event=False,
    )
    return app

