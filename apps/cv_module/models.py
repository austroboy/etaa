"""CV Module – Models."""

from django.db import models


class CVRankingJob(models.Model):
    """Represents a CV ranking run."""

    created_at       = models.DateTimeField(auto_now_add=True)
    job_requirements = models.TextField()
    source_type      = models.CharField(max_length=30)  # 'google_drive' | 'local'
    source_path      = models.CharField(max_length=500)
    top_n            = models.IntegerField(default=30)
    status           = models.CharField(max_length=20, default="pending")
    output_zip       = models.CharField(max_length=500, blank=True)
    total_cvs        = models.IntegerField(default=0)
    completed_at     = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"CVRanking#{self.pk} [{self.status}] – {self.total_cvs} CVs"


class CVCandidate(models.Model):
    """Individual candidate result row within a ranking job."""

    job         = models.ForeignKey(
        CVRankingJob, on_delete=models.CASCADE, related_name="candidates",
    )
    file_name           = models.CharField(max_length=255)
    candidate_name      = models.CharField(max_length=200, blank=True)
    match_score         = models.IntegerField(default=0)
    key_qualifications  = models.TextField(blank=True)
    rank                = models.IntegerField(default=0)

    current_designation = models.CharField(max_length=200, blank=True)
    current_company     = models.CharField(max_length=200, blank=True)
    years_experience    = models.IntegerField(default=0)
    relevant_industries = models.CharField(max_length=300, blank=True)
    email               = models.CharField(max_length=200, blank=True)
    phone               = models.CharField(max_length=50, blank=True)
    location            = models.CharField(max_length=120, blank=True)
    summary             = models.TextField(blank=True)

    class Meta:
        ordering = ["rank"]

    def __str__(self):
        return f"{self.candidate_name} – Score {self.match_score}"


class CandidateProfile(models.Model):
    """
    Global, deduplicated candidate record.

    One profile per real person, matched by email OR phone.
    When a candidate resubmits a CV, their profile is updated in-place
    instead of creating a duplicate.

    HR staff can annotate each profile with Remark, Rejected Company,
    and Others fields directly from the UI.
    """

    # ── Identity / dedup keys ────────────────────────────────────────────────
    email   = models.CharField(max_length=200, blank=True, db_index=True)
    phone   = models.CharField(max_length=50,  blank=True, db_index=True)

    # ── CV data (updated on each re-submission) ──────────────────────────────
    candidate_name      = models.CharField(max_length=200, blank=True)
    current_designation = models.CharField(max_length=200, blank=True)
    current_company     = models.CharField(max_length=200, blank=True)
    previous_designation= models.CharField(max_length=200, blank=True)
    previous_company    = models.CharField(max_length=200, blank=True)
    years_experience    = models.IntegerField(default=0)
    relevant_industries = models.CharField(max_length=300, blank=True)
    location            = models.CharField(max_length=120, blank=True)
    academic_qualification = models.CharField(max_length=300, blank=True)
    key_qualifications  = models.TextField(blank=True)
    summary             = models.TextField(blank=True)
    match_score         = models.IntegerField(default=0)
    rank                = models.IntegerField(default=0)
    file_name           = models.CharField(max_length=255, blank=True)

    # ── Link to the latest ranking job ───────────────────────────────────────
    latest_job = models.ForeignKey(
        CVRankingJob,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="profiles",
    )

    # ── HR annotations (editable from UI) ───────────────────────────────────
    remark           = models.TextField(blank=True, help_text="HR notes / remarks")
    rejected_company = models.TextField(blank=True, help_text="Companies candidate was rejected from")
    others           = models.TextField(blank=True, help_text="Extra notes")

    # ── Status ───────────────────────────────────────────────────────────────
    is_active = models.BooleanField(default=True)

    # ── Timestamps ───────────────────────────────────────────────────────────
    first_seen   = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-match_score", "rank"]
        verbose_name = "Candidate Profile"
        verbose_name_plural = "Candidate Profiles"

    def __str__(self):
        return f"{self.candidate_name} ({self.email or self.phone}) – {self.match_score}/100"