"""
Confirmation Module – Models
Tracks pending confirmations for sensitive operations.
"""

from django.db import models
from django.utils import timezone


class ConfirmationStatus(models.TextChoices):
    PENDING   = "pending",   "Pending"
    APPROVED  = "approved",  "Approved"
    DENIED    = "denied",    "Denied"
    EXPIRED   = "expired",   "Expired"


class PendingConfirmation(models.Model):
    """
    A sensitive action waiting for an authorized operator to confirm.
    """

    task_type          = models.CharField(max_length=50)
    description        = models.TextField(help_text="Human-readable description of the action to be taken.")
    payload            = models.JSONField(default=dict, help_text="Serialized task payload for execution after confirmation.")
    operator_phone     = models.CharField(max_length=30)
    operator_name      = models.CharField(max_length=120, blank=True)
    status             = models.CharField(max_length=20, choices=ConfirmationStatus.choices, default=ConfirmationStatus.PENDING)
    created_at         = models.DateTimeField(auto_now_add=True)
    expires_at         = models.DateTimeField()
    confirmed_at       = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def is_expired(self) -> bool:
        return timezone.now() > self.expires_at

    def approve(self):
        self.status = ConfirmationStatus.APPROVED
        self.confirmed_at = timezone.now()
        self.save(update_fields=["status", "confirmed_at"])

    def deny(self):
        self.status = ConfirmationStatus.DENIED
        self.confirmed_at = timezone.now()
        self.save(update_fields=["status", "confirmed_at"])

    def __str__(self):
        return f"Confirm#{self.pk} [{self.task_type}] – {self.status}"
