"""
Agent Module – Models.

Tracks dynamic agent runs (free-form instructions handled via LLM tool-use
loop) and the individual tool-call steps each run executes.
"""

from django.db import models


class AgentRunStatus(models.TextChoices):
    PENDING        = "pending",        "Pending"
    RUNNING        = "running",        "Running"
    AWAITING_CONF  = "awaiting_conf",  "Awaiting Confirmation"
    SUCCESS        = "success",        "Success"
    FAILED         = "failed",         "Failed"
    CANCELLED      = "cancelled",      "Cancelled"


class AgentRun(models.Model):
    """One free-form instruction executed by the dynamic agent loop."""

    created_at      = models.DateTimeField(auto_now_add=True)
    completed_at    = models.DateTimeField(null=True, blank=True)
    operator_phone  = models.CharField(max_length=30, blank=True)
    operator_name   = models.CharField(max_length=120, blank=True)
    instruction     = models.TextField()
    status          = models.CharField(max_length=20, choices=AgentRunStatus.choices,
                                       default=AgentRunStatus.PENDING)
    final_answer    = models.TextField(blank=True)
    error_detail    = models.TextField(blank=True)
    iterations      = models.IntegerField(default=0)
    # optional ID of the ActionLog entry this run is logged under
    log_id          = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"AgentRun#{self.pk} [{self.status}] – {self.instruction[:60]}"


class AgentStep(models.Model):
    """A single tool-call within an AgentRun (LLM decision + execution)."""

    run         = models.ForeignKey(AgentRun, on_delete=models.CASCADE, related_name="steps")
    step_number = models.IntegerField()
    tool_name   = models.CharField(max_length=80)
    tool_input  = models.JSONField(default=dict)
    tool_output = models.JSONField(default=dict, blank=True)
    success     = models.BooleanField(default=True)
    error       = models.TextField(blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["run", "step_number"]

    def __str__(self):
        return f"Run#{self.run_id}.step{self.step_number} {self.tool_name}"
