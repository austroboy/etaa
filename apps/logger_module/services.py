"""Logger Module – Service layer."""

import logging
from typing import Optional

logger = logging.getLogger("etaa")


def log_action(
    instruction_text: str,
    task_type: str,
    status: str,
    operator_name: str = "",
    operator_phone: str = "",
    output_location: str = "",
    error_detail: str = "",
    extra_data: Optional[dict] = None,
) -> "ActionLog":
    """Create and save an ActionLog entry. Returns the saved instance."""
    from apps.logger_module.models import ActionLog

    entry = ActionLog(
        instruction_text=instruction_text,
        task_type=task_type,
        status=status,
        operator_name=operator_name,
        operator_phone=operator_phone,
        output_location=output_location,
        error_detail=error_detail,
        extra_data=extra_data or {},
    )
    entry.save()
    logger.info(
        "ActionLog#%s | type=%s status=%s operator=%s",
        entry.pk,
        task_type,
        status,
        operator_name,
    )
    return entry


def update_log(log_id: int, **kwargs) -> None:
    """Update an existing ActionLog by primary key."""
    from apps.logger_module.models import ActionLog

    ActionLog.objects.filter(pk=log_id).update(**kwargs)
