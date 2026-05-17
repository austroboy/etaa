from django.urls import path
from .views import JobPostListView

urlpatterns = [
    path("", JobPostListView.as_view(), name="job-post-list"),
]
