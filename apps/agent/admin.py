"""Agent admin registrations."""

from django.contrib import admin

from apps.agent.models import AgentRun, AgentStep


@admin.register(AgentRun)
class AgentRunAdmin(admin.ModelAdmin):
    list_display = ("pk", "status", "operator_name", "iterations",
                    "created_at", "completed_at")
    list_filter = ("status",)
    search_fields = ("operator_name", "operator_phone", "instruction")
    readonly_fields = ("created_at", "completed_at")


@admin.register(AgentStep)
class AgentStepAdmin(admin.ModelAdmin):
    list_display = ("run", "step_number", "tool_name", "success", "created_at")
    list_filter = ("tool_name", "success")
    readonly_fields = ("created_at",)
