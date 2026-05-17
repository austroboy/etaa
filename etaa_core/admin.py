"""
ETAA Admin registrations.
Each module's admin is registered here for a unified admin panel.
"""

from django.contrib import admin

# ── Messaging ─────────────────────────────────────────────────────────────────
from apps.messaging.models import IncomingMessage

@admin.register(IncomingMessage)
class IncomingMessageAdmin(admin.ModelAdmin):
    list_display = ("received_at", "sender_name", "sender_phone", "is_authorized", "processed", "body_preview")
    list_filter  = ("is_authorized", "processed")
    search_fields = ("sender_name", "sender_phone", "body")
    readonly_fields = ("received_at",)

    def body_preview(self, obj):
        return obj.body[:80]
    body_preview.short_description = "Body Preview"


# ── Confirmation ──────────────────────────────────────────────────────────────
from apps.confirmation.models import PendingConfirmation

@admin.register(PendingConfirmation)
class PendingConfirmationAdmin(admin.ModelAdmin):
    list_display = ("pk", "task_type", "operator_name", "status", "created_at", "expires_at")
    list_filter  = ("status", "task_type")
    readonly_fields = ("created_at", "confirmed_at")


# ── Logger ────────────────────────────────────────────────────────────────────
from apps.logger_module.models import ActionLog

@admin.register(ActionLog)
class ActionLogAdmin(admin.ModelAdmin):
    list_display  = ("timestamp", "operator_name", "task_type", "status", "output_location")
    list_filter   = ("task_type", "status")
    search_fields = ("operator_name", "instruction_text")
    readonly_fields = ("timestamp",)


# ── Email ─────────────────────────────────────────────────────────────────────
from apps.email_module.models import EmailRecord

@admin.register(EmailRecord)
class EmailRecordAdmin(admin.ModelAdmin):
    list_display = ("sent_at", "direction", "to_address", "subject", "success")
    list_filter  = ("direction", "success")
    search_fields = ("to_address", "subject")
    readonly_fields = ("sent_at",)


# ── CV Ranking ────────────────────────────────────────────────────────────────
from apps.cv_module.models import CVRankingJob, CVCandidate

@admin.register(CVRankingJob)
class CVRankingJobAdmin(admin.ModelAdmin):
    list_display = ("pk", "status", "total_cvs", "top_n", "created_at")
    list_filter  = ("status",)
    readonly_fields = ("created_at", "completed_at")

@admin.register(CVCandidate)
class CVCandidateAdmin(admin.ModelAdmin):
    list_display = ("rank", "candidate_name", "match_score", "file_name", "job")
    list_filter  = ("job",)
    search_fields = ("candidate_name",)


# ── Job Post ──────────────────────────────────────────────────────────────────
from apps.job_post_module.models import JobPost

@admin.register(JobPost)
class JobPostAdmin(admin.ModelAdmin):
    list_display = ("job_title", "department", "status", "created_at")
    list_filter  = ("status",)
    search_fields = ("job_title",)
    readonly_fields = ("created_at",)


# ── Dev / Code Gen ────────────────────────────────────────────────────────────
from apps.dev_module.models import CodeGenerationJob

@admin.register(CodeGenerationJob)
class CodeGenerationJobAdmin(admin.ModelAdmin):
    list_display = ("pk", "tech_stack", "status", "git_pushed", "created_at")
    list_filter  = ("status", "tech_stack", "git_pushed")
    readonly_fields = ("created_at", "completed_at")
