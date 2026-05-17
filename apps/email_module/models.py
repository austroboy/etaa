"""Email Module – Models."""

from django.db import models


class EmailRecord(models.Model):
    """Log of every email sent or auto-replied."""

    class Direction(models.TextChoices):
        OUTBOUND = "outbound", "Outbound"
        INBOUND_REPLY = "inbound_reply", "Inbound Auto-Reply"

    direction      = models.CharField(max_length=20, choices=Direction.choices)
    to_address     = models.EmailField()
    cc_addresses   = models.TextField(blank=True)
    subject        = models.CharField(max_length=255)
    body_preview   = models.TextField(blank=True)
    template_used  = models.CharField(max_length=100, blank=True)
    sent_at        = models.DateTimeField(auto_now_add=True)
    success        = models.BooleanField(default=False)
    error_detail   = models.TextField(blank=True)

    class Meta:
        ordering = ["-sent_at"]

    def __str__(self):
        return f"[{self.direction}] {self.to_address} – {self.subject[:50]}"
