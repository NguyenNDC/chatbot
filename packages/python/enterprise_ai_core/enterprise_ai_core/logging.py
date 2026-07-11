import logging
import sys
import time
from uuid import uuid4

import structlog


def configure_logging(service_name: str) -> None:
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(message)s", force=True)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=True,
    )
    structlog.contextvars.bind_contextvars(service=service_name)


def get_logger(name: str | None = None):
    return structlog.get_logger(name)


def install_request_logging(app, service_name: str) -> None:
    logger = get_logger("http").bind(service=service_name)

    @app.middleware("http")
    async def log_requests(request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid4())
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            logger.exception(
                "request_failed",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                query=str(request.url.query),
                duration_ms=duration_ms,
                client=request.client.host if request.client else None,
            )
            raise

        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.info(
            "request_completed",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            query=str(request.url.query),
            status_code=response.status_code,
            duration_ms=duration_ms,
            client=request.client.host if request.client else None,
        )
        response.headers["X-Request-ID"] = request_id
        return response

