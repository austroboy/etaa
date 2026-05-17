"""
Confirmation Module – Service
Manages creation, lookup, and resolution of pending confirmations.
"""

import logging
from datetime import timedelta
from typing import Optional

from django.conf import settings
from django.utils import timezone

from apps.confirmation.models import PendingConfirmation, ConfirmationStatus

logger = logging.getLogger("etaa")

AFFIRMATIVE_KEYWORDS = {"yes", "y", "confirm", "ok", "okay", "approved", "go", "proceed", "sure"}
NEGATIVE_KEYWORDS    = {"no", "n", "cancel", "deny", "reject", "stop", "abort"}


def create_confirmation(
    task_type: str,
    description: str,
    payload: dict,
    operator_phone: str,
    operator_name: str = "",
) -> PendingConfirmation:
    """Create a new pending confirmation and return it."""
    timeout = settings.CONFIRMATION_TIMEOUT
    confirmation = PendingConfirmation.objects.create(
        task_type=task_type,
        description=description,
        payload=payload,
        operator_phone=operator_phone,
        operator_name=operator_name,
        expires_at=timezone.now() + timedelta(seconds=timeout),
    )
    logger.info(
        "Confirmation#%s created | task=%s operator=%s",
        confirmation.pk,
        task_type,
        operator_phone,
    )
    return confirmation


def get_pending_confirmation(operator_phone: str) -> Optional[PendingConfirmation]:
    """Return the most recent PENDING confirmation for the given operator, if any."""
    return (
        PendingConfirmation.objects.filter(
            operator_phone=operator_phone,
            status=ConfirmationStatus.PENDING,
        )
        .order_by("-created_at")
        .first()
    )


def process_confirmation_response(
    operator_phone: str,
    text: str,
) -> Optional[PendingConfirmation]:
    """
    Check if a message text is a confirmation response for a pending action.
    Returns the PendingConfirmation if it was resolved, else None.
    """
    confirmation = get_pending_confirmation(operator_phone)
    if confirmation is None:
        return None

    if confirmation.is_expired():
        confirmation.status = ConfirmationStatus.EXPIRED
        confirmation.save(update_fields=["status"])
        logger.info("Confirmation#%s expired.", confirmation.pk)
        return None

    normalized = text.strip().lower()
    # Tokenize on non-word characters so single-letter keywords like "y"
    # don't accidentally match substrings of longer words ("you", "yes").
    import re as _re
    tokens = set(_re.findall(r"\w+", normalized))

    if tokens & AFFIRMATIVE_KEYWORDS:
        confirmation.approve()
        logger.info("Confirmation#%s APPROVED by %s.",
                    confirmation.pk, operator_phone)
        return confirmation
    elif tokens & NEGATIVE_KEYWORDS:
        confirmation.deny()
        logger.info("Confirmation#%s DENIED by %s.",
                    confirmation.pk, operator_phone)
        return confirmation

    return None  # Not a confirmation response


def expire_stale_confirmations() -> int:
    """Mark all past-deadline pending confirmations as expired. Returns count."""
    count = PendingConfirmation.objects.filter(
        status=ConfirmationStatus.PENDING,
        expires_at__lt=timezone.now(),
    ).update(status=ConfirmationStatus.EXPIRED)
    if count:
        logger.info("Expired %d stale confirmations.", count)
    return count
