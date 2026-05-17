"""CV Module – Django Admin."""

from django.contrib import admin
from .models import CVRankingJob, CVCandidate, CandidateProfile


@admin.register(CVRankingJob)
class CVRankingJobAdmin(admin.ModelAdmin):
    list_display  = ("pk", "status", "total_cvs", "top_n", "created_at")
    list_filter   = ("status", "source_type")
    readonly_fields = ("created_at", "completed_at")


@admin.register(CVCandidate)
class CVCandidateAdmin(admin.ModelAdmin):
    list_display  = ("candidate_name", "match_score", "rank", "job", "email", "phone")
    list_filter   = ("job",)
    search_fields = ("candidate_name", "email", "phone")


@admin.register(CandidateProfile)
class CandidateProfileAdmin(admin.ModelAdmin):
    list_display  = (
        "candidate_name", "match_score", "current_designation",
        "current_company", "email", "phone", "is_active", "last_updated",
    )
    list_filter   = ("is_active",)
    search_fields = ("candidate_name", "email", "phone", "current_company")
    readonly_fields = ("first_seen", "last_updated")
    fieldsets = (
        ("Identity", {"fields": ("candidate_name", "email", "phone")}),
        ("Current Role", {"fields": ("current_designation", "current_company")}),
        ("Previous Role", {"fields": ("previous_designation", "previous_company")}),
        ("Details", {"fields": (
            "years_experience", "relevant_industries", "location",
            "academic_qualification", "match_score", "rank", "file_name",
        )}),
        ("Long Text", {"fields": ("key_qualifications", "summary")}),
        ("HR Annotations", {"fields": ("remark", "rejected_company", "others")}),
        ("Status", {"fields": ("is_active", "latest_job")}),
        ("Timestamps", {"fields": ("first_seen", "last_updated")}),
    )