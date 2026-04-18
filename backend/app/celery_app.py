"""
Celery application configuration for background task processing.
"""
from celery import Celery
from app.config import settings

# Create Celery app
celery_app = Celery(
    "synkro",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=['app.tasks.meeting_tasks', 'app.tasks.integration_tasks']  # Auto-discover tasks
)

# Celery configuration
celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 minutes max per task
    task_soft_time_limit=25 * 60,  # 25 minutes soft limit
    worker_prefetch_multiplier=1,  # One task at a time
    worker_max_tasks_per_child=50,  # Restart worker after 50 tasks
    # Run tasks synchronously in-process when broker is unavailable (dev mode)
    task_always_eager=True,
    task_eager_propagates=False,
)

# Task routing (optional - for organizing tasks)
celery_app.conf.task_routes = {
    'app.tasks.meeting_tasks.transcribe_meeting_task': {'queue': 'meetings'},
    'app.tasks.meeting_tasks.summarize_meeting_task': {'queue': 'meetings'},
}

# Beat schedule for periodic tasks (optional)
celery_app.conf.beat_schedule = {
    # Example: Clean up old meetings every day
    # 'cleanup-old-meetings': {
    #     'task': 'app.tasks.cleanup_tasks.cleanup_old_meetings',
    #     'schedule': crontab(hour=0, minute=0),  # Run at midnight
    # },
}
