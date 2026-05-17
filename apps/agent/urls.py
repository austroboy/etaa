from django.urls import path

from apps.agent.views import AgentRunListView, AgentRunDetailView

urlpatterns = [
    path("runs/", AgentRunListView.as_view(), name="agent-runs"),
    path("runs/<int:pk>/", AgentRunDetailView.as_view(), name="agent-run-detail"),
]
