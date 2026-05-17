"""Confirmation Module – Celery Tasks."""

from celery import shared_task


@shared_task(name="apps.confirmation.tasks.expire_confirmations_task")
def expire_confirmations_task():
    """Expire all stale (past-deadline) pending confirmations."""
    from apps.confirmation.services import expire_stale_confirmations
    count = expire_stale_confirmations()
    return f"Expired {count} confirmations"
