"""Job Post Module – Models."""

from django.db import models


class JobPost(models.Model):
    """Tracks a generated job post."""

    created_at        = models.DateTimeField(auto_now_add=True)
    job_title         = models.CharField(max_length=200)
    department        = models.CharField(max_length=100, blank=True)
    description_text  = models.TextField(blank=True)
    canva_design_id   = models.CharField(max_length=200, blank=True)
    jpg_path          = models.CharField(max_length=500, blank=True)
    status            = models.CharField(max_length=20, default="pending")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.job_title} [{self.status}]"
