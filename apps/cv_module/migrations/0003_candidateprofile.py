"""Migration: Add CandidateProfile (global, deduplicated by email/phone)."""

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("cv_module", "0002_cvcandidate_current_company_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="CandidateProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                # Identity (dedup keys)
                ("email",               models.CharField(max_length=200, blank=True, db_index=True)),
                ("phone",               models.CharField(max_length=50,  blank=True, db_index=True)),
                # Core info
                ("candidate_name",      models.CharField(max_length=200, blank=True)),
                ("current_designation", models.CharField(max_length=200, blank=True)),
                ("current_company",     models.CharField(max_length=200, blank=True)),
                ("previous_designation",models.CharField(max_length=200, blank=True)),
                ("previous_company",    models.CharField(max_length=200, blank=True)),
                ("years_experience",    models.IntegerField(default=0)),
                ("relevant_industries", models.CharField(max_length=300, blank=True)),
                ("location",            models.CharField(max_length=120, blank=True)),
                ("academic_qualification", models.CharField(max_length=300, blank=True)),
                ("key_qualifications",  models.TextField(blank=True)),
                ("summary",             models.TextField(blank=True)),
                ("match_score",         models.IntegerField(default=0)),
                ("rank",                models.IntegerField(default=0)),
                ("file_name",           models.CharField(max_length=255, blank=True)),
                # Link to latest ranking job
                ("latest_job",          models.ForeignKey(
                    "cv_module.CVRankingJob",
                    null=True, blank=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="profiles",
                )),
                # HR editable fields
                ("remark",              models.TextField(blank=True, help_text="HR notes / remarks")),
                ("rejected_company",    models.TextField(blank=True, help_text="Companies candidate was rejected from")),
                ("others",              models.TextField(blank=True, help_text="Extra notes")),
                # Status
                ("is_active",           models.BooleanField(default=True)),
                # Timestamps
                ("first_seen",          models.DateTimeField(auto_now_add=True)),
                ("last_updated",        models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["-match_score", "rank"],
                "verbose_name": "Candidate Profile",
                "verbose_name_plural": "Candidate Profiles",
            },
        ),
    ]