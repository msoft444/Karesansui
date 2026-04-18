import os

from celery import Celery

# Redis connection URL is injected via REDIS_URL environment variable.
# The default value mirrors the docker-compose service name.
REDIS_URL: str = os.environ.get("REDIS_URL", "redis://redis:6379/0")

# Celery application instance shared by all task modules.
celery_app = Celery(
    "karesansui",
    broker=REDIS_URL,
    backend=REDIS_URL,
)

celery_app.conf.update(
    # Serialise task payloads and results as JSON for portability and security.
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # UTC timestamps throughout.
    timezone="UTC",
    enable_utc=True,
    # Acknowledge tasks only after they finish (or raise) to avoid silent loss
    # if the worker process is killed mid-execution.
    task_acks_late=True,
    # Do not pre-fetch more than one task at a time so retried tasks do not
    # starve behind a long-running sibling.
    worker_prefetch_multiplier=1,
    # Auto-discover tasks registered in app.tasks.
    include=["app.tasks"],
)
