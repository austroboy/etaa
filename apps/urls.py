"""Aggregate URL router for all ETAA apps."""

from django.urls import path, include

urlpatterns = [
    path("messaging/", include("apps.messaging.urls")),
    path("email/",     include("apps.email_module.urls")),
    path("cv/",        include("apps.cv_module.urls")),
    path("jobpost/",   include("apps.job_post_module.urls")),
    path("dev/",       include("apps.dev_module.urls")),
    path("agent/",     include("apps.agent.urls")),
    path("authz/",     include("apps.authz.urls")),
    path("confirm/",   include("apps.confirmation.urls")),
    path("logs/",      include("apps.logger_module.urls")),
]

# Health check (no auth required)
from django.http import JsonResponse
from django.urls import path as _path

def health(request):
    return JsonResponse({"status": "ok", "service": "ETAA"})

urlpatterns += [_path("health/", health, name="health-check")]
