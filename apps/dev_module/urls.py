from django.urls import path
from .views import CodeGenJobListView

urlpatterns = [
    path("jobs/", CodeGenJobListView.as_view(), name="codegen-job-list"),
]
