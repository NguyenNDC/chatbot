from enterprise_ai_core.queue import get_celery_app

celery_app = get_celery_app()

import tasks  # noqa: E402,F401

