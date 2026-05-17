from django.urls import path
from .views import (
    CVRankingJobListView,
    CandidateProfileListView,
    CandidateProfileDetailView,
    CandidateAutocompleteView,
    CVDashboardUIView,
)

urlpatterns = [
    # Existing
    path("jobs/",                       CVRankingJobListView.as_view(),       name="cv-job-list"),
    # New: Candidate profiles
    path("profiles/",                   CandidateProfileListView.as_view(),   name="cv-profile-list"),
    path("profiles/autocomplete/",      CandidateAutocompleteView.as_view(),  name="cv-profile-autocomplete"),
    path("profiles/<int:pk>/",          CandidateProfileDetailView.as_view(), name="cv-profile-detail"),
    # UI dashboard
    path("ui/",                         CVDashboardUIView.as_view(),          name="cv-dashboard-ui"),
]