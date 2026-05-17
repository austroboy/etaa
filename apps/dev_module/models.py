"""Dev Module – Models."""

from django.db import models


class CodeGenerationJob(models.Model):
    """Tracks a code generation run from an SRS document."""

    created_at     = models.DateTimeField(auto_now_add=True)
    srs_text       = models.TextField(blank=True)
    srs_file_path  = models.CharField(max_length=500, blank=True)
    tech_stack     = models.CharField(max_length=100, default="django")
    output_dir     = models.CharField(max_length=500, blank=True)
    git_pushed     = models.BooleanField(default=False)
    repo_url       = models.CharField(max_length=500, blank=True)
    status         = models.CharField(max_length=20, default="pending")
    completed_at   = models.DateTimeField(null=True, blank=True)
    error_detail   = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"CodeGen#{self.pk} [{self.tech_stack}] – {self.status}"
