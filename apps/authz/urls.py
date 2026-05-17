from django.urls import path

from apps.authz.views import (
    AuthorizationEventListView,
    GroupMembershipListView,
)

urlpatterns = [
    path("memberships/", GroupMembershipListView.as_view(),
         name="authz-memberships"),
    path("events/", AuthorizationEventListView.as_view(),
         name="authz-events"),
]
