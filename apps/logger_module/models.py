"""
Logger Module – Models
Persistent audit log for all ETAA actions.
"""

from django.db import models


class TaskType(models.TextChoices):
    EMAIL_OUTBOUND = "email_outbound", "Email – Outbound"
    EMAIL_INBOUND  = "email_inbound",  "Email – Inbound Reply"
    CV_RANKING     = "cv_ranking",     "CV Ranking & Filtering"
    JOB_POST       = "job_post",       "Job Post Creation"
    CODE_GEN       = "code_gen",       "Software Code Generation"
    GIT_PUSH       = "git_push",       "Git Push"
    CONFIRMATION   = "confirmation",   "Confirmation Request"
    UNKNOWN        = "unknown",        "Unknown / Unclassified"


class TaskStatus(models.TextChoices):
    PENDING   = "pending",   "Pending"
    CONFIRMED = "confirmed", "Confirmed"
    IN_PROGRESS = "in_progress", "In Progress"
    SUCCESS   = "success",   "Success"
    FAILED    = "failed",    "Failed"
    CANCELLED = "cancelled", "Cancelled"
    REJECTED  = "rejected",  "Rejected (Unauthorised)"


class ActionLog(models.Model):
    """Immutable audit record for every task the Agent processes."""

    timestamp        = models.DateTimeField(auto_now_add=True, db_index=True)
    operator_name    = models.CharField(max_length=120, blank=True)
    operator_phone   = models.CharField(max_length=30, blank=True)
    instruction_text = models.TextField()
    task_type        = models.CharField(max_length=30, choices=TaskType.choices, default=TaskType.UNKNOWN)
    status           = models.CharField(max_length=20, choices=TaskStatus.choices, default=TaskStatus.PENDING)
    output_location  = models.TextField(blank=True)
    error_detail     = models.TextField(blank=True)
    llm_cost_usd     = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    extra_data       = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-timestamp"]
        verbose_name = "Action Log"
        verbose_name_plural = "Action Logs"

    def __str__(self):
        return f"[{self.timestamp:%Y-%m-%d %H:%M}] {self.task_type} – {self.status}"
