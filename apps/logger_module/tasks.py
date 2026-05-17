"""Logger Module – Periodic Tasks."""

from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from django.conf import settings


@shared_task
def purge_old_logs_task():
    """Delete action logs older than LOG_RETENTION_DAYS."""
    from apps.logger_module.models import ActionLog

    retention_days = getattr(settings, "LOG_RETENTION_DAYS", 90)
    cutoff = timezone.now() - timedelta(days=retention_days)
    deleted, _ = ActionLog.objects.filter(timestamp__lt=cutoff).delete()
    return f"Purged {deleted} old log entries"
