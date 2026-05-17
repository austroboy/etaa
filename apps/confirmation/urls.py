from django.urls import path
from .views import ConfirmationResponseView

urlpatterns = [
    path("respond/", ConfirmationResponseView.as_view(), name="confirm-respond"),
]
