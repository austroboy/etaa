from django.urls import path
from .views import EmailRecordListView

urlpatterns = [
    path("records/", EmailRecordListView.as_view(), name="email-records"),
]
