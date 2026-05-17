"""Messaging Module – Models."""

from django.db import models


class IncomingMessage(models.Model):
    """Raw record of every WhatsApp message received."""

    received_at   = models.DateTimeField(auto_now_add=True)
    sender_phone  = models.CharField(max_length=30)
    sender_name   = models.CharField(max_length=120, blank=True)
    group_jid     = models.CharField(max_length=100, blank=True)
    message_id    = models.CharField(max_length=100, unique=True)
    body          = models.TextField()
    media_url     = models.URLField(blank=True)
    is_authorized = models.BooleanField(default=False)
    processed     = models.BooleanField(default=False)

    class Meta:
        ordering = ["-received_at"]

    def __str__(self):
        return f"[{self.received_at:%H:%M}] {self.sender_name}: {self.body[:60]}"
